import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import LoggingSettings
from app.logging_config import (
    ConsoleLogHandler, DailyLogHandler, LogFormatter, configure_logging,
    log_context, shutdown_logging,
)


def emit(handler, message, *, event="queue_empty", **fields):
    record = logging.LogRecord("app.api_client", logging.INFO, __file__, 1, message, (), None)
    record.event = event
    record.statusCode = 204 if event == "queue_empty" else 200
    for key, value in fields.items():
        setattr(record, key, value)
    handler.handle(record)


@pytest.fixture
def logfile(tmp_path):
    path = tmp_path / "printer-agent.log"
    handler = DailyLogHandler(path, retention_files=3)
    handler.setFormatter(LogFormatter())
    yield path, handler
    handler.close()


def test_consecutive_empty_polls_keep_latest_line_and_truncate_old_bytes(logfile):
    path, handler = logfile
    emit(handler, "Agente iniciado", event="agent_started")
    for index in range(500):
        emit(handler, "HTTP 204 No Content de Facturación " + "x" * 100,
             printerId="facturacion", ip="192.168.1.87", durationMs=index)
    emit(handler, "HTTP 204 No Content", printerId="pista", ip="192.168.1.22")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "Agente iniciado" in lines[0]
    assert "printerId=pista" in lines[1]
    assert "192.168.1.87" not in lines[1]
    assert "x" * 10 not in lines[1]
    assert path.stat().st_size < 1000


def test_significant_event_breaks_empty_poll_sequence(logfile):
    path, handler = logfile
    emit(handler, "HTTP 204 No Content: primero")
    emit(handler, "Trabajo reclamado", event="job_claimed", jobId="job-1")
    emit(handler, "HTTP 204 No Content: anterior")
    emit(handler, "HTTP 204 No Content: ultimo")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert "primero" in lines[0]
    assert "Trabajo reclamado" in lines[1]
    assert "ultimo" in lines[2]


def test_reopening_recovers_only_the_empty_tail(logfile):
    path, handler = logfile
    emit(handler, "Error conservado", event="job_failed")
    emit(handler, "HTTP 204 No Content: viejo")
    handler.close()
    reopened = DailyLogHandler(path, retention_files=3)
    reopened.setFormatter(LogFormatter())
    try:
        emit(reopened, "HTTP 204 No Content: nuevo")
    finally:
        reopened.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "Error conservado" in lines[0]
    assert "nuevo" in lines[1]


def test_rotation_preserves_previous_day_empty_tail_and_limits_history(tmp_path, monkeypatch):
    now = time.mktime((2026, 1, 1, 23, 59, 58, 0, 0, -1))
    monkeypatch.setattr("logging.handlers.time.time", lambda: now)
    path = tmp_path / "printer-agent.log"
    handler = DailyLogHandler(path, retention_files=3)
    handler.setFormatter(LogFormatter())
    try:
        emit(handler, "HTTP 204 No Content: dia 1")
        now += 5
        emit(handler, "HTTP 204 No Content: dia 2")
        archive = tmp_path / "printer-agent.log.2026-01-01"
        assert "dia 1" in archive.read_text(encoding="utf-8")
        assert "dia 2" in path.read_text(encoding="utf-8")
        for day in range(3, 8):
            now += 86400
            emit(handler, f"HTTP 204 No Content: dia {day}")
        assert len(list(tmp_path.glob("printer-agent.log*"))) == 3
        assert "dia 7" in path.read_text(encoding="utf-8")
    finally:
        handler.close()


def test_exception_traceback_is_not_replaced_by_empty_poll(logfile):
    path, handler = logfile
    try:
        raise TimeoutError("private exception argument")
    except TimeoutError:
        import sys
        record = logging.LogRecord("app.worker", logging.ERROR, __file__, 1,
                                   "Fallo", (), sys.exc_info())
        record.event = "job_failed"
        handler.handle(record)
    emit(handler, "HTTP 204 No Content: antiguo")
    emit(handler, "HTTP 204 No Content: reciente")
    text = path.read_text(encoding="utf-8")
    assert "Traceback" in text and "TimeoutError" in text
    assert "private exception argument" not in text
    assert "antiguo" not in text and "reciente" in text


def test_only_explicit_empty_events_are_compacted(logfile):
    path, handler = logfile
    emit(handler, "Un error menciona No Content", event="job_failed")
    emit(handler, "HTTP 204 No Content")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_disk_failure_warns_once_recovers_and_does_not_raise(tmp_path, capsys):
    parent = tmp_path / "blocked"
    parent.write_text("not a directory")
    handler = DailyLogHandler(parent / "printer-agent.log", retention_files=3)
    handler.setFormatter(LogFormatter())
    try:
        emit(handler, "HTTP 204 No Content")
        emit(handler, "HTTP 204 No Content")
        assert capsys.readouterr().err.count("No se pueden persistir") == 1
        parent.unlink()
        emit(handler, "HTTP 204 No Content: recuperado")
        assert "Se recuperó" in capsys.readouterr().err
        assert "recuperado" in (parent / "printer-agent.log").read_text(encoding="utf-8")
    finally:
        handler.close()


def test_runtime_write_failure_does_not_raise(logfile, monkeypatch, capsys):
    path, handler = logfile
    emit(handler, "Trabajo anterior", event="job_claimed")
    with monkeypatch.context() as patch:
        def denied(*_args, **_kwargs):
            raise OSError("disk full")
        patch.setattr(handler.stream, "write", denied)
        emit(handler, "Nuevo trabajo", event="job_claimed")
    assert "No se pueden persistir" in capsys.readouterr().err
    emit(handler, "Trabajo recuperado", event="job_claimed")
    assert "Se recuperó" in capsys.readouterr().err
    text = path.read_text(encoding="utf-8")
    assert "Trabajo anterior" in text and "Trabajo recuperado" in text


def test_console_suppresses_consecutive_empty_events_but_keeps_other_records(capsys):
    handler = ConsoleLogHandler()
    handler.setFormatter(LogFormatter())
    try:
        emit(handler, "HTTP 204 No Content: primero")
        emit(handler, "HTTP 204 No Content: repetido")
        emit(handler, "Trabajo", event="job_claimed")
        emit(handler, "HTTP 204 No Content: nuevo")
    finally:
        handler.close()
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 3
    assert "primero" in output and "Trabajo" in output and "nuevo" in output
    assert "repetido" not in output


def test_parallel_writes_preserve_every_significant_event(logfile):
    path, handler = logfile
    def send(index):
        emit(handler, f"Trabajo numero {index}", event="job_claimed", jobId=f"job-{index}")
        emit(handler, "HTTP 204 No Content", printerId="facturacion")
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(send, range(100)))
    lines = path.read_text(encoding="utf-8").splitlines()
    for index in range(100):
        assert sum(line.endswith(f"Trabajo numero {index}") for line in lines) == 1


def test_prune_removes_only_own_archives(tmp_path):
    for day in range(1, 6):
        (tmp_path / f"printer-agent.log.2026-01-{day:02d}").write_text("old")
    unrelated = tmp_path / "other.log.2026-01-01"
    unrelated.write_text("preserve")
    handler = DailyLogHandler(tmp_path / "printer-agent.log", retention_files=3)
    try:
        handler.prune_history()
        assert len(list(tmp_path.glob("printer-agent.log.*"))) == 2
        assert unrelated.exists()
    finally:
        handler.close()


def test_configure_is_idempotent_and_uvicorn_logs_are_persisted(configured_logs):
    path, settings = configured_logs
    configure_logging(settings)
    logging.getLogger("uvicorn.error").info("Arranque probado")
    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /health HTTP/1.1" 200')
    text = path.read_text(encoding="utf-8")
    assert text.count("Arranque probado") == 1
    assert text.count("GET /health") == 1
    assert "agentId=test-agent" in text
    console = next(handler for handler in logging.getLogger().handlers if isinstance(handler, ConsoleLogHandler))
    assert console.stream.getvalue().count("Arranque probado") == 1


def test_secrets_and_validation_inputs_are_not_logged(configured_logs):
    from pydantic import BaseModel, ValidationError
    path, _ = configured_logs
    logger = logging.getLogger("app.worker")
    logger.info("api-secret-value Authorization: Bearer another-secret")
    class Model(BaseModel):
        amount: int
    try:
        Model(amount="PRIVATE TICKET CONTENT")
    except ValidationError:
        logger.exception("Respuesta inválida", extra={"event": "claim_failed"})
    text = path.read_text(encoding="utf-8")
    assert "api-secret-value" not in text
    assert "another-secret" not in text
    assert "PRIVATE TICKET CONTENT" not in text
    assert "ValidationError" in text and "int_parsing" in text


async def test_context_survives_threads_without_leaking_between_workers(configured_logs):
    path, _ = configured_logs
    logger = logging.getLogger("app.printer")
    async def send(printer_id):
        with log_context(printerId=printer_id, jobId="job-" + printer_id):
            await asyncio.to_thread(logger.info, "Envío", extra={"event": "tcp_sent"})
    await asyncio.gather(send("facturacion"), send("pista"))
    logger.info("Sin trabajo", extra={"event": "worker_stopped"})
    lines = path.read_text(encoding="utf-8").splitlines()
    for printer_id in ("facturacion", "pista"):
        line = next(line for line in lines if f"jobId=job-{printer_id}" in line)
        assert f"printerId={printer_id}" in line
    assert "jobId=" not in lines[-1] and "printerId=" not in lines[-1]

import asyncio
import json
import logging

import httpx
import pytest

from app.api_client import PrintQueueClient
from app.config import Settings
from app.printer import LanPrinter
from app.worker import PrintWorker


@pytest.fixture
async def trace_agent(configured_logs, monkeypatch):
    path, logging_settings = configured_logs
    settings = Settings(_env_file=None, log_dir=path.parent,
                        system_api_url="https://test.example.com",
                        print_agent_api_key=logging_settings.print_agent_api_key,
                        printers=[{"name": "Facturación", "ip": "192.168.1.87"},
                                  {"name": "Pista", "ip": "192.168.1.22"}])
    state = {"fail": None, "claimed": set(), "results": [], "payloads": []}

    def respond(request):
        body = json.loads(request.content)
        printer_id = body["printerId"]
        if request.url.path.endswith("/claim"):
            if state["fail"] == "claim":
                return httpx.Response(500)
            if printer_id in state["claimed"]:
                return httpx.Response(204)
            state["claimed"].add(printer_id)
            return httpx.Response(200, json={
                "id": "job-" + printer_id, "printerId": printer_id,
                "documentType": "cobro", "attempts": 2,
                "payload": {"version": 1, "widthMm": 108, "heightMm": 30,
                            "elements": [{"type": "text", "xMm": 0, "yMm": 0,
                                          "text": "PRIVATE_TICKET_CONTENT"}]},
            })
        state["results"].append(body)
        return httpx.Response(500 if state["fail"] == "result" else 200)

    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def settimeout(self, _timeout):
            pass
        def sendall(self, payload):
            if state["fail"] == "send":
                raise TimeoutError("PRIVATE_TICKET_CONTENT")
            state["payloads"].append(payload)

    def connect(address, timeout):
        assert address[1] == 9100
        if state["fail"] == "connect":
            raise TimeoutError("PRIVATE_TICKET_CONTENT")
        return Socket()

    monkeypatch.setattr("app.printer.socket.create_connection", connect)
    client = PrintQueueClient(settings)
    await client._client.aclose()
    client._client = httpx.AsyncClient(base_url=settings.system_api_url,
                                     transport=httpx.MockTransport(respond))
    printers = [LanPrinter(settings, config) for config in settings.printers]
    workers = [PrintWorker(client, printer, 2, printer.config.printer_id,
                           log_fields=printer.log_fields) for printer in printers]
    try:
        yield path, state, workers
    finally:
        await client.close()


async def test_full_trace_correlates_two_printers_and_coalesces_idle_polls(trace_agent):
    path, state, workers = trace_agent
    assert await asyncio.gather(*(worker.run_once() for worker in workers)) == [True, True]
    assert len(state["payloads"]) == 2
    for _ in range(10):
        assert await asyncio.gather(*(worker.run_once() for worker in workers)) == [False, False]
    lines = path.read_text(encoding="utf-8").splitlines()
    for printer_id, ip in (("facturacion", "192.168.1.87"), ("pista", "192.168.1.22")):
        job_lines = [line for line in lines if f"jobId=job-{printer_id}" in line]
        assert len(job_lines) == 5
        for line in job_lines:
            assert f"printerId={printer_id}" in line and f"ip={ip}" in line
            assert "attempt=2" in line
        events = [line.split("event=", 1)[1].split()[0] for line in job_lines]
        assert events == ["job_claimed", "tcp_send_started", "tcp_connected", "tcp_sent", "result_confirmed"]
        assert "salida física no verificada" in job_lines[3]
    assert sum("event=queue_empty" in line for line in lines) == 1
    assert "jobId=" not in lines[-1]
    assert "PRIVATE_TICKET_CONTENT" not in "\n".join(lines)
    assert "api-secret-value" not in "\n".join(lines)


@pytest.mark.parametrize("stage", ["claim", "connect", "send", "compile", "result"])
async def test_failure_stage_is_visible_without_leaking_payload(trace_agent, monkeypatch, stage):
    path, state, workers = trace_agent
    state["fail"] = stage
    if stage == "compile":
        def fail_compile(*_args, **_kwargs):
            raise ValueError("PRIVATE_TICKET_CONTENT")
        monkeypatch.setattr("app.printer.compile_tspl", fail_compile)
    assert await workers[0].run_once() is (stage != "claim")
    text = path.read_text(encoding="utf-8")
    assert "PRIVATE_TICKET_CONTENT" not in text
    assert "printerId=facturacion" in text
    if stage == "claim":
        assert "event=claim_failed" in text and "HTTP 500" in text
        assert state["results"] == []
    elif stage == "result":
        assert text.index("event=tcp_sent") < text.index("event=result_failed")
        assert "event=result_confirmed" not in text
        assert "HTTP 500" in text
        assert len(state["payloads"]) == 1
    else:
        assert "event=job_failed" in text
        assert f"stage={'compile' if stage == 'compile' else 'tcp_' + stage}" in text
        assert "event=tcp_sent" not in text
        assert state["results"][0]["status"] == "failed"
        assert "result=failed" in text


async def test_worker_start_and_stop_are_logged(trace_agent):
    path, _, workers = trace_agent
    stop = asyncio.Event()
    stop.set()
    await workers[0].run(stop)
    text = path.read_text(encoding="utf-8")
    assert "event=worker_started" in text and "event=worker_stopped" in text


def test_debug_does_not_enable_http_body_or_header_traces(configured_logs):
    from app.logging_config import configure_logging
    path, settings = configured_logs
    configure_logging(settings.model_copy(update={"log_level": "DEBUG"}))
    logging.getLogger("httpcore.http11").debug("PRIVATE_TICKET_CONTENT")
    logging.getLogger("httpx").info("HTTP 204 No Content automatico")
    text = path.read_text(encoding="utf-8")
    assert "PRIVATE_TICKET_CONTENT" not in text and "automatico" not in text


async def test_logging_write_failure_does_not_interrupt_printing(trace_agent, monkeypatch):
    from app.logging_config import DailyLogHandler
    _, state, workers = trace_agent
    handler = next(handler for handler in logging.getLogger().handlers if isinstance(handler, DailyLogHandler))
    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(handler.stream, "write", fail_write)
    assert await workers[0].run_once() is True
    assert len(state["payloads"]) == 1
    assert state["results"][0]["status"] == "sent"

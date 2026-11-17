import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from app.config import Settings
from app.logging_config import DailyLogHandler


def test_launcher_configures_logging_before_uvicorn_and_closes_handlers(configured_logs, monkeypatch):
    from app import __main__ as entry
    path, settings = configured_logs
    monkeypatch.setattr(entry, "LoggingSettings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["printer-agent", "--host", "127.0.0.1", "--port", "8123"])
    def run(app_path, **options):
        assert app_path == "app.main:app"
        assert options == {"host": "127.0.0.1", "port": 8123, "workers": 1, "log_config": None}
        logging.getLogger("uvicorn.error").info("Server arrancado")
        logging.getLogger("uvicorn.error").info("Server detenido")
    monkeypatch.setattr(entry.uvicorn, "run", run)
    entry.main()
    text = path.read_text(encoding="utf-8")
    assert "Server arrancado" in text and "Server detenido" in text
    assert not any(isinstance(handler, DailyLogHandler) for handler in logging.getLogger().handlers)


async def test_lifespan_records_destination_and_shutdown_without_network(configured_logs, monkeypatch):
    import app.main as main
    path, settings = configured_logs
    config = Settings(_env_file=None, log_dir=path.parent,
                      system_api_url="https://test.example.com", print_agent_api_key="api-secret-value",
                      print_agent_id=settings.print_agent_id,
                      printers=[{"name": "Facturación", "ip": "127.0.0.1"}])
    started = asyncio.Event()
    closed = []
    class Queue:
        def __init__(self, _settings):
            pass
        async def claim(self, printer_id):
            assert printer_id == "facturacion"
            started.set()
            return None
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(main, "LoggingSettings", lambda: settings)
    monkeypatch.setattr(main, "get_settings", lambda: config)
    monkeypatch.setattr(main, "PrintQueueClient", Queue)
    async with main.lifespan(main.app):
        await asyncio.wait_for(started.wait(), 2)
        assert (await main.health())["printers"][0]["printerId"] == "facturacion"
    assert closed == [True]
    text = path.read_text(encoding="utf-8")
    assert "event=agent_started" in text and "event=agent_stopped" in text
    assert "event=worker_started" in text and "event=worker_stopped" in text
    assert "event=printer_configured" in text and "printerName=Facturación" in text


def test_new_process_preserves_existing_history(tmp_path):
    project = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({"PYTHONPATH": str(project), "LOG_DIR": str(tmp_path / "logs"),
                        "LOG_LEVEL": "INFO", "LOG_RETENTION_FILES": "14",
                        "PRINT_AGENT_ID": "test-process", "PRINT_AGENT_API_KEY": "test-secret"})
    script = (
        "import logging,sys; from app.config import LoggingSettings; "
        "from app.logging_config import configure_logging,shutdown_logging; "
        "configure_logging(LoggingSettings()); "
        "logging.getLogger('uvicorn.error').info('Ejecucion '+sys.argv[1]); shutdown_logging()"
    )
    for number in ("1", "2"):
        result = subprocess.run([sys.executable, "-c", script, number], cwd=tmp_path,
                                env=environment, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
    text = (tmp_path / "logs" / "printer-agent.log").read_text(encoding="utf-8")
    assert text.count("Ejecucion 1") == 1 and text.count("Ejecucion 2") == 1


def test_invalid_configuration_is_logged_without_input_values(tmp_path):
    project = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({"PYTHONPATH": str(project), "LOG_DIR": str(tmp_path / "logs"),
                        "LOG_LEVEL": "INFO", "LOG_RETENTION_FILES": "14",
                        "PRINT_AGENT_ID": "test-process", "PRINT_AGENT_API_KEY": "test-secret",
                        "SYSTEM_API_URL": "https://test.example.com",
                        "PRINTERS": '[{"name":"Pista","ip":"127.0.0.1"}]',
                        "PRINTER_PORT": "PRIVATE_CONFIG_VALUE"})
    result = subprocess.run([sys.executable, "-m", "app", "--host", "127.0.0.1", "--port", "0"],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    text = (tmp_path / "logs" / "printer-agent.log").read_text(encoding="utf-8")
    assert "event=configuration_failed" in text
    assert "printer_port (int_parsing)" in text
    for output in (text, result.stdout, result.stderr):
        assert "PRIVATE_CONFIG_VALUE" not in output
        assert "test-secret" not in output

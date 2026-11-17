import io
import logging

import pytest

from app.config import LoggingSettings
from app.logging_config import ConsoleLogHandler, configure_logging, shutdown_logging


@pytest.fixture
def configured_logs(tmp_path, capsys):
    root = logging.getLogger()
    previous_root_level = root.level
    names = ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore")
    saved = {name: (logging.getLogger(name).level, logging.getLogger(name).propagate,
                    list(logging.getLogger(name).handlers)) for name in names}
    settings = LoggingSettings(_env_file=None, log_dir=tmp_path,
                               print_agent_api_key="api-secret-value", print_agent_id="test-agent")
    configure_logging(settings)
    # Un stream estable evita depender de los cambios de captura entre fases de pytest.
    for handler in root.handlers:
        if isinstance(handler, ConsoleLogHandler):
            handler.stream = io.StringIO()
    try:
        yield tmp_path / "printer-agent.log", settings
    finally:
        shutdown_logging()
        root.setLevel(previous_root_level)
        for name, (level, propagate, handlers) in saved.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.propagate = propagate
            logger.handlers = handlers


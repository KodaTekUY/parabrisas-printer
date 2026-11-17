"""Logging local, con rotación diaria y reemplazo del último polling vacío.

Un solo proceso escribe cada archivo. El lock del handler serializa los workers
async y los hilos usados para enviar TCP. Docker recibe una salida sin repeticiones.
"""

import logging
import os
import re
import sys
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from .config import LoggingSettings

_CONTEXT: ContextVar[dict[str, object]] = ContextVar("print_log_context", default={})
_FIELDS = (
    "agentId", "printerId", "printerName", "ip", "port", "jobId", "attempt",
    "documentType", "stage", "statusCode", "result", "bytes", "durationMs", "errorType",
)
_HANDLER_PREFIX = "parabrisas."
_configuration: tuple | None = None


@contextmanager
def log_context(**fields: object) -> Iterator[None]:
    token = _CONTEXT.set({**_CONTEXT.get(), **fields})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def is_empty_poll(record: logging.LogRecord) -> bool:
    return getattr(record, "event", None) == "queue_empty" and getattr(record, "statusCode", None) == 204


class ContextFilter(logging.Filter):
    def __init__(self, agent_id: str):
        super().__init__()
        self.agent_id = agent_id

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in {"agentId": self.agent_id, **_CONTEXT.get()}.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class LogFormatter(logging.Formatter):
    def __init__(self, secret: str = ""):
        super().__init__()
        self.secret = secret

    def clean(self, value: object) -> str:
        text = str(value)
        if self.secret:
            text = text.replace(self.secret, "[REDACTED]")
        text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
        return text.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")

    def formatException(self, exc_info) -> str:
        # Las representaciones de ValidationError, UnicodeError, etc. pueden
        # contener el ticket o secretos. Guardamos tipos, códigos y frames,
        # nunca argumentos, valores de entrada, variables locales ni código fuente.
        error = exc_info[1]
        parts = ["Traceback (sin datos de entrada):"]
        for frame, lineno in traceback.walk_tb(exc_info[2]):
            parts.append(f"  File {self.clean(frame.f_code.co_filename)}, line {lineno}, in {frame.f_code.co_name}")
        details = [type(error).__name__]
        response = getattr(error, "response", None)
        if response is not None and hasattr(response, "status_code"):
            details.append(f"HTTP {response.status_code}")
        if isinstance(error, OSError) and error.errno is not None:
            details.append(f"errno={error.errno}")
        if isinstance(error, ValidationError):
            for item in error.errors(include_input=False, include_url=False, include_context=False):
                location = ".".join(map(str, item["loc"]))
                details.append(f"{self.clean(location)} ({item['type']})")
        parts.append(": ".join(details))
        return "\n".join(parts)

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds")
        event = self.clean(getattr(record, "event", "runtime"))
        context = " ".join(f"{key}={self.clean(getattr(record, key))}" for key in _FIELDS if hasattr(record, key))
        line = f"{timestamp} {record.levelname} {record.name} event={event}"
        if context:
            line += " " + context
        line += " - " + self.clean(record.getMessage())
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class ConsoleLogHandler(logging.StreamHandler):
    """La consola de Docker no permite reemplazar entradas ya capturadas."""

    def __init__(self):
        super().__init__(sys.stdout)
        self._previous_empty = False

    def emit(self, record: logging.LogRecord) -> None:
        empty = is_empty_poll(record)
        if not (empty and self._previous_empty):
            super().emit(record)
        self._previous_empty = empty


class DailyLogHandler(TimedRotatingFileHandler):
    def __init__(self, filename: str | Path, *, retention_files: int):
        if retention_files < 2:
            raise ValueError("La retención debe incluir al menos el archivo activo y un histórico")
        self._empty_offset: int | None = None
        self._last_end: int | None = None
        self._write_failed = False
        super().__init__(filename, when="midnight", backupCount=retention_files - 1,
                         encoding="utf-8", errors="backslashreplace", delay=True)

    def _open(self):
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        # LF también en Windows: offsets de bytes estables para truncar la cola.
        stream = open(self.baseFilename, self.mode, encoding=self.encoding,
                      errors=self.errors, newline="\n")
        self._recover_empty_tail()
        return stream

    def _recover_empty_tail(self) -> None:
        self._empty_offset = None
        self._last_end = None
        try:
            with open(self.baseFilename, "rb") as existing:
                size = existing.seek(0, os.SEEK_END)
                start = max(0, size - 8192)
                existing.seek(start)
                tail = existing.read()
            if not tail.endswith(b"\n"):
                return
            line_start = tail.rfind(b"\n", 0, len(tail) - 1) + 1
            if line_start == 0 and start != 0:
                return
            last_line = tail[line_start:-1].decode("utf-8")
            header = last_line.split(" - ", 1)[0]
            if re.match(r"^\d{4}-\d\d-\d\dT\S+ \w+ [\w.]+ event=queue_empty(?: |$)", header) and "statusCode=204" in header.split():
                self._empty_offset = start + line_start
                self._last_end = size
        except (OSError, UnicodeError):
            # Si sólo se permite escribir, se sigue anexando y se compactan
            # las siguientes consultas de este proceso.
            pass

    @staticmethod
    def _notice(message: str, error: Exception | None = None) -> None:
        try:
            detail = f" ({type(error).__name__})" if error else ""
            sys.stderr.write(f"WARNING logging: {message}{detail}\n")
            sys.stderr.flush()
        except Exception:
            pass  # Una falla de logging nunca debe detener una impresión.

    def prune_history(self) -> None:
        if not Path(self.baseFilename).parent.is_dir():
            return
        try:
            for filename in self.getFilesToDelete():
                os.remove(filename)
        except OSError as error:
            self._notice("No se pudo aplicar la retención del historial", error)

    def doRollover(self) -> None:
        self._empty_offset = None
        self._last_end = None
        super().doRollover()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Rotar antes de considerar el reemplazo: nunca sobrescribir el día anterior.
            if self.shouldRollover(record):
                self.doRollover()
            if self.stream is None:
                self.stream = self._open()
            text = self.format(record) + self.terminator
            empty = is_empty_poll(record) and not record.exc_info
            end = self.stream.seek(0, os.SEEK_END)
            if empty and self._empty_offset is not None and end == self._last_end:
                # En modo append, seek no cambia el destino de write. Se trunca
                # solamente el último No Content antes de anexar su reemplazo.
                self.stream.seek(self._empty_offset)
                self.stream.truncate()
            start = self.stream.seek(0, os.SEEK_END)
            self.stream.write(text)
            self.stream.flush()
            self._last_end = self.stream.tell()
            self._empty_offset = start if empty else None
            if self._write_failed:
                self._write_failed = False
                self._notice("Se recuperó la persistencia de logs")
        except Exception as error:
            self._empty_offset = None
            self._last_end = None
            if self.stream is not None:
                try:
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
            if not self._write_failed:
                self._notice("No se pueden persistir logs; el agente continúa con salida por consola", error)
            self._write_failed = True


def shutdown_logging() -> None:
    global _configuration
    root = logging.getLogger()
    for handler in list(root.handlers):
        if (handler.name or "").startswith(_HANDLER_PREFIX):
            root.removeHandler(handler)
            handler.close()
    _configuration = None


def configure_logging(settings: LoggingSettings) -> None:
    global _configuration
    secret = settings.print_agent_api_key.get_secret_value() if settings.print_agent_api_key else ""
    configuration = (str(settings.log_dir.resolve()), settings.log_level,
                     settings.log_retention_files, settings.print_agent_id, secret)
    if configuration == _configuration:
        return
    shutdown_logging()
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    formatter = LogFormatter(secret)
    context_filter = ContextFilter(settings.print_agent_id)
    console = ConsoleLogHandler()
    console.name = _HANDLER_PREFIX + "console"
    handlers: list[logging.Handler] = [console]
    try:
        persistent = DailyLogHandler(settings.log_dir / "printer-agent.log",
                                     retention_files=settings.log_retention_files)
        persistent.name = _HANDLER_PREFIX + "file"
        persistent.prune_history()
        handlers.append(persistent)
    except OSError as error:
        # El handler con apertura diferida reintenta errores normales de escritura.
        # Esto cubre además fallos al inspeccionar el archivo durante su construcción.
        DailyLogHandler._notice("Persistencia no disponible; el agente continúa con salida por consola", error)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = True
        logger.setLevel(settings.log_level)
    # Evitar tanto el polling duplicado como el volcado de headers en DEBUG.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    _configuration = configuration
    logging.getLogger(__name__).info("Registro en consola y archivo configurado", extra={"event": "logging_ready"})

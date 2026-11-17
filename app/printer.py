import asyncio
import logging
import socket
from time import perf_counter

from .config import PrinterConfig, Settings
from .logging_config import log_context
from .models import PrintDocument
from .tspl import compile_tspl

logger = logging.getLogger(__name__)


class LanPrinter:
    def __init__(self, settings: Settings, printer: PrinterConfig):
        self._settings = settings
        self.config = printer
        self._lock = asyncio.Lock()

    @property
    def log_fields(self) -> dict[str, object]:
        return {"printerId": self.config.printer_id, "printerName": self.config.name,
                "ip": str(self.config.ip), "port": self._settings.printer_port}

    def _send_bytes(self, payload: bytes) -> None:
        started = perf_counter()
        stage = "tcp_connect"
        logger.info("Iniciando envío TCP", extra={"event": "tcp_send_started", "bytes": len(payload)})
        try:
            with socket.create_connection(
                (str(self.config.ip), self._settings.printer_port),
                timeout=self._settings.printer_timeout_seconds,
            ) as connection:
                logger.info("Conexión TCP establecida", extra={
                    "event": "tcp_connected", "stage": stage,
                    "durationMs": round((perf_counter() - started) * 1000, 2),
                })
                stage = "tcp_send"
                connection.settimeout(self._settings.printer_timeout_seconds)
                connection.sendall(payload)
        except Exception as error:
            logger.error("Falló la operación TCP", extra={
                "event": "tcp_failed", "stage": stage, "errorType": type(error).__name__,
                "durationMs": round((perf_counter() - started) * 1000, 2),
            })
            raise
        logger.info("Envío TCP completado; salida física no verificada", extra={
            "event": "tcp_sent", "bytes": len(payload),
            "durationMs": round((perf_counter() - started) * 1000, 2),
        })

    async def print_document(self, document: PrintDocument) -> None:
        with log_context(**self.log_fields):
            try:
                payload = compile_tspl(
                    document,
                    dpi=self._settings.printer_dpi,
                    encoding=self._settings.printer_encoding,
                    codepage=self._settings.printer_codepage,
                )
            except Exception as error:
                logger.error("No se pudo generar el documento TSPL", extra={
                    "event": "document_failed", "stage": "compile", "errorType": type(error).__name__,
                })
                raise
            async with self._lock:
                await asyncio.to_thread(self._send_bytes, payload)

    async def health(self) -> bool:
        def connect() -> bool:
            with socket.create_connection(
                (str(self.config.ip), self._settings.printer_port),
                timeout=self._settings.printer_timeout_seconds,
            ):
                return True

        try:
            return await asyncio.to_thread(connect)
        except OSError:
            return False

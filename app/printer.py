import asyncio
import socket

from .config import PrinterConfig, Settings
from .models import PrintDocument
from .tspl import compile_tspl


class LanPrinter:
    def __init__(self, settings: Settings, printer: PrinterConfig):
        self._settings = settings
        self.config = printer
        self._lock = asyncio.Lock()

    def _send_bytes(self, payload: bytes) -> None:
        with socket.create_connection(
            (str(self.config.ip), self._settings.printer_port),
            timeout=self._settings.printer_timeout_seconds,
        ) as connection:
            connection.settimeout(self._settings.printer_timeout_seconds)
            connection.sendall(payload)

    async def print_document(self, document: PrintDocument) -> None:
        payload = compile_tspl(
            document,
            dpi=self._settings.printer_dpi,
            encoding=self._settings.printer_encoding,
            codepage=self._settings.printer_codepage,
        )
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

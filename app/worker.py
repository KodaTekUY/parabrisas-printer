import asyncio
import logging
from collections.abc import Awaitable, Callable

from .api_client import PrintQueueClient
from .printer import LanPrinter

logger = logging.getLogger(__name__)


class PrintWorker:
    def __init__(
        self,
        client: PrintQueueClient,
        printer: LanPrinter,
        poll_interval_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._client = client
        self._printer = printer
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep = sleep

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                pass

    async def run_once(self) -> bool:
        try:
            job = await self._client.claim()
        except Exception:
            logger.exception("No se pudo consultar la cola de impresión")
            return False

        if job is None:
            return False

        try:
            await self._printer.print_document(job.payload)
        except Exception as error:
            logger.exception("Falló la impresión %s", job.id)
            try:
                await self._client.report_failed(job.id, str(error) or type(error).__name__)
            except Exception:
                logger.exception("No se pudo reportar el fallo de %s", job.id)
            return True

        try:
            await self._client.report_sent(job.id)
        except Exception:
            logger.exception("La impresora recibió %s pero no se pudo confirmar al servidor", job.id)
        return True

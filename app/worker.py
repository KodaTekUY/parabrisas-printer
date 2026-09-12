import asyncio
import logging
from collections.abc import Awaitable, Callable

from .api_client import PrintQueueClient
from .config import PrinterId
from .printer import LanPrinter

logger = logging.getLogger(__name__)


class PrintWorker:
    def __init__(
        self,
        client: PrintQueueClient,
        printer: LanPrinter,
        poll_interval_seconds: float,
        printer_id: PrinterId,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._client = client
        self._printer = printer
        self._poll_interval_seconds = poll_interval_seconds
        self._printer_id = printer_id
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
            job = await self._client.claim(self._printer_id)
        except Exception:
            logger.exception("No se pudo consultar la cola de impresión [%s]", self._printer_id)
            return False

        if job is None:
            return False

        if job.printer_id != self._printer_id:
            logger.error("Destino incorrecto para %s: esperado %s, recibido %s", job.id, self._printer_id, job.printer_id)
            return False

        try:
            await self._printer.print_document(job.payload)
        except Exception as error:
            logger.exception("Falló la impresión %s [%s]", job.id, self._printer_id)
            try:
                await self._client.report_failed(job.id, self._printer_id, str(error) or type(error).__name__)
            except Exception:
                logger.exception("No se pudo reportar el fallo de %s [%s]", job.id, self._printer_id)
            return True

        try:
            await self._client.report_sent(job.id, self._printer_id)
            logger.info("Impresión enviada %s [%s]", job.id, self._printer_id)
        except Exception:
            logger.exception("La impresora recibió %s [%s] pero no se pudo confirmar al servidor", job.id, self._printer_id)
        return True

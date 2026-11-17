import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter

from .api_client import PrintQueueClient
from .config import PrinterId
from .logging_config import log_context
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
        *,
        log_fields: Mapping[str, object] | None = None,
    ):
        self._client = client
        self._printer = printer
        self._poll_interval_seconds = poll_interval_seconds
        self._printer_id = printer_id
        self._sleep = sleep
        self._log_fields = {**(log_fields or {}), "printerId": printer_id}

    async def run(self, stop: asyncio.Event) -> None:
        with log_context(**self._log_fields):
            logger.info("Worker iniciado", extra={"event": "worker_started"})
            try:
                while not stop.is_set():
                    await self.run_once()
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_seconds)
                    except TimeoutError:
                        pass
            except Exception:
                logger.exception("Worker terminado por un error inesperado", extra={"event": "worker_failed"})
                raise
            finally:
                logger.info("Worker detenido", extra={"event": "worker_stopped"})

    async def run_once(self) -> bool:
        with log_context(**self._log_fields):
            return await self._run_once()

    async def _run_once(self) -> bool:
        started = perf_counter()
        try:
            job = await self._client.claim(self._printer_id)
        except Exception:
            logger.exception("No se pudo consultar la cola de impresión", extra={
                "event": "claim_failed", "stage": "api_claim",
                "durationMs": round((perf_counter() - started) * 1000, 2),
            })
            return False

        if job is None:
            return False

        if job.printer_id != self._printer_id:
            logger.error("Destino incorrecto: esperado %s, recibido %s", self._printer_id, job.printer_id,
                         extra={"event": "routing_failed", "stage": "api_claim", "jobId": job.id})
            return False

        with log_context(jobId=job.id, attempt=job.attempts, documentType=job.document_type):
            logger.info("Trabajo reclamado", extra={
                "event": "job_claimed", "stage": "api_claim",
                "durationMs": round((perf_counter() - started) * 1000, 2),
            })
            started = perf_counter()
            try:
                await self._printer.print_document(job.payload)
            except Exception as error:
                logger.exception("Falló el envío del trabajo de impresión", extra={
                    "event": "job_failed", "stage": "printing",
                    "durationMs": round((perf_counter() - started) * 1000, 2),
                })
                try:
                    await self._client.report_failed(job.id, self._printer_id, str(error) or type(error).__name__)
                except Exception:
                    logger.exception("No se pudo reportar el fallo al servidor", extra={
                        "event": "result_failed", "stage": "api_result", "result": "failed",
                    })
                return True

            started = perf_counter()
            try:
                await self._client.report_sent(job.id, self._printer_id)
            except Exception:
                logger.exception("Envío TCP finalizado, pero no se pudo confirmar el resultado al servidor", extra={
                    "event": "result_failed", "stage": "api_result", "result": "sent",
                    "durationMs": round((perf_counter() - started) * 1000, 2),
                })
            return True

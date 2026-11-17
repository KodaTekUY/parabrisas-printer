import logging
from time import perf_counter

import httpx

from .config import PrinterId, Settings
from .models import ClaimedPrintJob

logger = logging.getLogger(__name__)


class PrintQueueClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.normalized_api_url(),
            headers={
                "Authorization": f"Bearer {settings.print_agent_api_key.get_secret_value()}",
                "User-Agent": f"parabrisas-printer/{settings.print_agent_id}",
            },
            timeout=settings.api_timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def claim(self, printer_id: PrinterId) -> ClaimedPrintJob | None:
        started = perf_counter()
        response = await self._client.post(
            "/api/printing/jobs/claim",
            json={"agentId": self._settings.print_agent_id, "printerId": printer_id},
        )
        if response.status_code == 204:
            logger.info("HTTP 204 No Content; sin trabajos disponibles", extra={
                "event": "queue_empty", "printerId": printer_id, "statusCode": 204,
                "durationMs": round((perf_counter() - started) * 1000, 2),
            })
            return None
        response.raise_for_status()
        job = ClaimedPrintJob.model_validate(response.json())
        if job.printer_id != printer_id:
            raise ValueError("La API devolvió una impresión de otro destino")
        return job

    async def report_sent(self, job_id: str, printer_id: PrinterId) -> None:
        await self._report(job_id, printer_id, status="sent")

    async def report_failed(self, job_id: str, printer_id: PrinterId, error: str) -> None:
        await self._report(job_id, printer_id, status="failed", error=error[:1000] or "Error de impresión")

    async def _report(self, job_id: str, printer_id: PrinterId, *, status: str, error: str | None = None) -> None:
        payload: dict[str, str] = {
            "agentId": self._settings.print_agent_id,
            "printerId": printer_id,
            "status": status,
        }
        if error:
            payload["error"] = error
        started = perf_counter()
        response = await self._client.post(
            f"/api/printing/jobs/{job_id}/result",
            json=payload,
        )
        response.raise_for_status()
        logger.info("Servidor confirmó el resultado del trabajo", extra={
            "event": "result_confirmed", "stage": "api_result", "jobId": job_id,
            "printerId": printer_id, "result": status, "statusCode": response.status_code,
            "durationMs": round((perf_counter() - started) * 1000, 2),
        })

import httpx

from .config import Settings
from .models import ClaimedPrintJob


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

    async def claim(self) -> ClaimedPrintJob | None:
        response = await self._client.post(
            "/api/printing/jobs/claim",
            json={"agentId": self._settings.print_agent_id},
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return ClaimedPrintJob.model_validate(response.json())

    async def report_sent(self, job_id: str) -> None:
        await self._report(job_id, status="sent")

    async def report_failed(self, job_id: str, error: str) -> None:
        await self._report(job_id, status="failed", error=error[:1000] or "Error de impresión")

    async def _report(self, job_id: str, *, status: str, error: str | None = None) -> None:
        payload: dict[str, str] = {
            "agentId": self._settings.print_agent_id,
            "status": status,
        }
        if error:
            payload["error"] = error
        response = await self._client.post(
            f"/api/printing/jobs/{job_id}/result",
            json=payload,
        )
        response.raise_for_status()

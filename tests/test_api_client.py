import json

import httpx
import pytest

from app.api_client import PrintQueueClient
from app.config import Settings


async def test_claim_and_result_include_the_worker_destination(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(204 if request.url.path.endswith("claim") else 200)

    client = httpx.AsyncClient(base_url="https://test.example.com", transport=httpx.MockTransport(handle))
    monkeypatch.setattr("app.api_client.httpx.AsyncClient", lambda **kwargs: client)
    api = PrintQueueClient(Settings(_env_file=None, system_api_url="https://test.example.com",
        print_agent_api_key="secret", printers=[{"name": "Pista", "ip": "192.168.1.53"}]))
    try:
        assert await api.claim("pista") is None
        await api.report_sent("job-1", "pista")
        await api.report_failed("job-2", "pista", "offline")
    finally:
        await api.close()
    bodies = [json.loads(request.content) for request in requests]
    assert all(body["printerId"] == "pista" for body in bodies)
    assert bodies[1]["status"] == "sent"
    assert bodies[2]["error"] == "offline"


async def test_rejects_job_for_other_printer(monkeypatch):
    def handle(request):
        return httpx.Response(200, json={"id": "job-1", "printerId": "facturacion", "documentType": "operativa", "attempts": 1,
            "payload": {"version": 1, "widthMm": 108, "heightMm": 30,
                "elements": [{"type": "text", "xMm": 0, "yMm": 0, "text": "OT"}]}})

    client = httpx.AsyncClient(base_url="https://test.example.com", transport=httpx.MockTransport(handle))
    monkeypatch.setattr("app.api_client.httpx.AsyncClient", lambda **kwargs: client)
    api = PrintQueueClient(Settings(_env_file=None, system_api_url="https://test.example.com",
        print_agent_api_key="secret", printers=[{"name": "Pista", "ip": "192.168.1.53"}]))
    try:
        with pytest.raises(ValueError, match="otro destino"):
            await api.claim("pista")
    finally:
        await api.close()

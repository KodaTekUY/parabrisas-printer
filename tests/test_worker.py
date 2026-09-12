from app.models import ClaimedPrintJob
from app.worker import PrintWorker


JOB = ClaimedPrintJob.model_validate(
    {
        "id": "job-1",
        "printerId": "facturacion",
        "documentType": "cobro",
        "attempts": 1,
        "payload": {
            "version": 1,
            "widthMm": 108,
            "heightMm": 30,
            "gapMm": 0,
            "copies": 1,
            "speed": 4,
            "density": 8,
            "elements": [
                {
                    "type": "text",
                    "xMm": 4,
                    "yMm": 4,
                    "text": "PARABRISAS",
                    "font": "4",
                    "xScale": 1,
                    "yScale": 1,
                    "rotation": 0,
                }
            ],
        },
    }
)


class FakeClient:
    def __init__(self):
        self.job = JOB
        self.sent: list[str] = []
        self.failed: list[tuple[str, str]] = []

    async def claim(self, printer_id):
        assert printer_id == "facturacion"
        job, self.job = self.job, None
        return job

    async def report_sent(self, job_id: str, printer_id: str):
        assert printer_id == "facturacion"
        self.sent.append(job_id)

    async def report_failed(self, job_id: str, printer_id: str, error: str):
        assert printer_id == "facturacion"
        self.failed.append((job_id, error))


class FakePrinter:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def print_document(self, _document):
        self.calls += 1
        if self.error:
            raise self.error


async def test_worker_reports_sent_after_printing() -> None:
    client = FakeClient()
    printer = FakePrinter()
    worker = PrintWorker(client, printer, 2, "facturacion")

    assert await worker.run_once() is True
    assert printer.calls == 1
    assert client.sent == ["job-1"]
    assert client.failed == []


async def test_worker_reports_printer_failure() -> None:
    client = FakeClient()
    printer = FakePrinter(ConnectionError("offline"))
    worker = PrintWorker(client, printer, 2, "facturacion")

    assert await worker.run_once() is True
    assert client.sent == []
    assert client.failed == [("job-1", "offline")]


async def test_worker_rejects_another_destination() -> None:
    client = FakeClient()
    client.job = JOB.model_copy(update={"printer_id": "pista"})
    printer = FakePrinter()
    worker = PrintWorker(client, printer, 2, "facturacion")
    assert await worker.run_once() is False
    assert printer.calls == 0
    assert client.sent == []


async def test_slow_printer_does_not_block_another_worker() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowPrinter(FakePrinter):
        async def print_document(self, document):
            started.set()
            await release.wait()
            raise ConnectionError("offline")

    class PistaClient(FakeClient):
        async def claim(self, printer_id):
            assert printer_id == "pista"
            job, self.job = self.job, None
            return job

        async def report_sent(self, job_id, printer_id):
            assert printer_id == "pista"
            self.sent.append(job_id)

    slow_client = FakeClient()
    fast_client = PistaClient()
    fast_client.job = JOB.model_copy(update={"id": "job-pista", "printer_id": "pista"})
    slow = PrintWorker(slow_client, SlowPrinter(), 2, "facturacion")
    fast = PrintWorker(fast_client, FakePrinter(), 2, "pista")
    task = asyncio.create_task(slow.run_once())
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert await asyncio.wait_for(fast.run_once(), 1) is True
        assert fast_client.sent == ["job-pista"]
        assert not task.done()
    finally:
        release.set()
        await task
    assert slow_client.failed == [("job-1", "offline")]
import asyncio

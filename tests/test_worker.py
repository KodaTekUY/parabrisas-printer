from app.models import ClaimedPrintJob
from app.worker import PrintWorker


JOB = ClaimedPrintJob.model_validate(
    {
        "id": "job-1",
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

    async def claim(self):
        job, self.job = self.job, None
        return job

    async def report_sent(self, job_id: str):
        self.sent.append(job_id)

    async def report_failed(self, job_id: str, error: str):
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
    worker = PrintWorker(client, printer, 2)

    assert await worker.run_once() is True
    assert printer.calls == 1
    assert client.sent == ["job-1"]
    assert client.failed == []


async def test_worker_reports_printer_failure() -> None:
    client = FakeClient()
    printer = FakePrinter(ConnectionError("offline"))
    worker = PrintWorker(client, printer, 2)

    assert await worker.run_once() is True
    assert client.sent == []
    assert client.failed == [("job-1", "offline")]

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api_client import PrintQueueClient
from .config import get_settings
from .printer import LanPrinter
from .worker import PrintWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = PrintQueueClient(settings)
    printer = LanPrinter(settings)
    worker = PrintWorker(client, printer, settings.poll_interval_seconds)
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop), name="print-polling-worker")
    app.state.printer = printer
    app.state.worker_task = task
    try:
        yield
    finally:
        stop.set()
        await task
        await client.close()


app = FastAPI(
    title="Parabrisas Printer",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    settings = get_settings()
    return {
        "ok": True,
        "agentId": settings.print_agent_id,
        "printer": f"{settings.printer_host}:{settings.printer_port}",
    }


@app.get("/health/printer")
async def printer_health():
    printer: LanPrinter = app.state.printer
    connected = await printer.health()
    return {"ok": connected}

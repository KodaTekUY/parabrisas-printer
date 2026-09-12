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
    stop = asyncio.Event()
    printers = [LanPrinter(settings, config) for config in settings.printers]
    tasks = [asyncio.create_task(
        PrintWorker(client, printer, settings.poll_interval_seconds, printer.config.printer_id).run(stop),
        name=f"print-worker-{printer.config.printer_id}",
    ) for printer in printers]
    app.state.printers = printers
    app.state.worker_tasks = tasks
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.gather(*tasks)
        finally:
            await client.close()


app = FastAPI(
    title="Parabrisas Printer",
    version="0.2.0",
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
        "printers": [{"printerId": printer.printer_id, "name": printer.name,
                      "ip": str(printer.ip), "port": settings.printer_port}
                     for printer in settings.printers],
    }


@app.get("/health/printer")
async def printer_health():
    printers: list[LanPrinter] = app.state.printers
    connected = await asyncio.gather(*(printer.health() for printer in printers))
    return {"ok": all(connected), "printers": [
        {"printerId": printer.config.printer_id, "name": printer.config.name, "ok": ok}
        for printer, ok in zip(printers, connected, strict=True)
    ]}

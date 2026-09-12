import asyncio

from app.config import Settings
from app.models import PrintDocument
from app.printer import LanPrinter


async def test_sends_to_configured_ip_and_port(monkeypatch):
    connections = []
    payloads = []

    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): pass
        def sendall(self, payload): payloads.append(payload)

    def connect(address, timeout):
        connections.append(address)
        return Socket()

    monkeypatch.setattr("app.printer.socket.create_connection", connect)
    config = Settings(_env_file=None, system_api_url="https://test.example.com",
        print_agent_api_key="secret", printers=[{"name": "Pista", "ip": "192.168.1.53"}])
    printer = LanPrinter(config, config.printers[0])
    document = PrintDocument.model_validate({"version": 1, "widthMm": 108, "heightMm": 30,
        "elements": [{"type": "text", "xMm": 0, "yMm": 0, "text": "OT"}]})
    await printer.print_document(document)
    assert await printer.health() is True
    assert connections == [("192.168.1.53", 9100), ("192.168.1.53", 9100)]
    assert b"PRINT 1" in payloads[0]


async def test_printer_serializes_sends(monkeypatch):
    import threading
    config = Settings(_env_file=None, system_api_url="https://test.example.com",
        print_agent_api_key="secret", printers=[{"name": "Pista", "ip": "192.168.1.53"}])
    printer = LanPrinter(config, config.printers[0])
    gate = threading.Event()
    started = threading.Event()
    calls = []

    def send(payload):
        calls.append(payload)
        started.set()
        gate.wait(2)

    monkeypatch.setattr(printer, "_send_bytes", send)
    doc = PrintDocument.model_validate({"version": 1, "widthMm": 108, "heightMm": 30,
        "elements": [{"type": "text", "xMm": 0, "yMm": 0, "text": "OT"}]})
    first = asyncio.create_task(printer.print_document(doc))
    second = asyncio.create_task(printer.print_document(doc))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert len(calls) == 1
    finally:
        gate.set()
        await asyncio.gather(first, second)
    assert len(calls) == 2

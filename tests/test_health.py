from app.config import Settings
from app.main import app, health, printer_health


async def test_health_identifies_each_destination(monkeypatch):
    config = Settings(_env_file=None, system_api_url="https://test.example.com", print_agent_api_key="secret",
        printers=[{"name": "Pista", "ip": "192.168.1.53"}, {"name": "Facturación", "ip": "192.168.1.50"}])
    monkeypatch.setattr("app.main.get_settings", lambda: config)

    class Printer:
        def __init__(self, config, online):
            self.config = config
            self.online = online
        async def health(self): return self.online

    monkeypatch.setattr(app.state, "printers", [Printer(config.printers[0], True), Printer(config.printers[1], False)], raising=False)
    assert (await health())["printers"] == [
        {"printerId": "pista", "name": "Pista", "ip": "192.168.1.53", "port": 9100},
        {"printerId": "facturacion", "name": "Facturación", "ip": "192.168.1.50", "port": 9100},
    ]
    assert await printer_health() == {"ok": False, "printers": [
        {"printerId": "pista", "name": "Pista", "ok": True},
        {"printerId": "facturacion", "name": "Facturación", "ok": False},
    ]}

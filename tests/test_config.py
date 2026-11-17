import pytest
from pydantic import ValidationError

from app.config import Settings


def settings(printers):
    return Settings(_env_file=None, system_api_url="https://test.example.com",
                    print_agent_api_key="secret", printers=printers)


def test_accepts_four_named_printers_with_stable_ids():
    config = settings([
        {"name": "Mostrador 1", "ip": "192.168.1.51"},
        {"name": "Mostrador 2", "ip": "192.168.1.52"},
        {"name": "Facturación", "ip": "192.168.1.50"},
        {"name": "Pista", "ip": "192.168.1.53"},
    ])
    assert [printer.printer_id for printer in config.printers] == [
        "mostrador_1", "mostrador_2", "facturacion", "pista",
    ]
    assert config.printer_port == 9100


@pytest.mark.parametrize("printers", [
    [],
    [{"name": "Otra", "ip": "192.168.1.1"}],
    [{"name": "Pista", "ip": "hostname-not-ip"}],
    [{"name": "Pista", "ip": "999.168.1.1"}],
    [{"name": "Pista", "ip": "192.168.1.1"}, {"name": "Pista", "ip": "192.168.1.2"}],
    [{"name": "Pista", "ip": "192.168.1.1"}, {"name": "Facturación", "ip": "192.168.1.1"}],
])
def test_rejects_invalid_or_ambiguous_configuration(printers):
    with pytest.raises(ValidationError):
        settings(printers)


def test_reads_json_environment(monkeypatch):
    monkeypatch.setenv("PRINTERS", '[{"name":"Facturación","ip":"192.168.1.50"}]')
    config = Settings(_env_file=None, system_api_url="https://test.example.com", print_agent_api_key="secret")
    assert config.printers[0].printer_id == "facturacion"


@pytest.mark.parametrize("values", [
    {"log_retention_files": 0}, {"log_retention_files": 1},
    {"log_level": "verbose"}, {"log_dir": "   "},
])
def test_rejects_invalid_logging_configuration(values):
    from app.config import LoggingSettings
    with pytest.raises(ValidationError):
        LoggingSettings(_env_file=None, **values)


def test_logging_settings_work_before_api_configuration_is_available():
    from app.config import LoggingSettings
    config = LoggingSettings(_env_file=None, log_level="info")
    assert config.log_level == "INFO"
    assert config.log_retention_files == 14
    assert str(config.log_dir) == "logs"

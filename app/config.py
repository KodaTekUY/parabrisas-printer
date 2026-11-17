from functools import lru_cache
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PrinterId = Literal["mostrador_1", "mostrador_2", "facturacion", "pista"]
PrinterName = Literal["Mostrador 1", "Mostrador 2", "Facturación", "Pista"]
PRINTER_IDS: dict[PrinterName, PrinterId] = {
    "Mostrador 1": "mostrador_1",
    "Mostrador 2": "mostrador_2",
    "Facturación": "facturacion",
    "Pista": "pista",
}


class PrinterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: PrinterName
    ip: IPv4Address | IPv6Address

    @property
    def printer_id(self) -> PrinterId:
        return PRINTER_IDS[self.name]


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_dir: Path = Path("logs")
    log_retention_files: int = Field(default=14, ge=2, le=366)
    print_agent_id: str = Field(default="xp470l-01", pattern=r"^[a-zA-Z0-9._-]{1,64}$")
    print_agent_api_key: SecretStr | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("log_dir", mode="before")
    @classmethod
    def validate_log_dir(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("LOG_DIR no puede estar vacío")
        return value


class Settings(LoggingSettings):
    system_api_url: str = Field(min_length=8)
    print_agent_api_key: SecretStr

    printers: list[PrinterConfig] = Field(min_length=1, max_length=4)
    printer_port: int = Field(default=9100, ge=1, le=65535)
    printer_dpi: int = Field(default=203, ge=100, le=600)
    printer_encoding: str = "utf-8"
    printer_codepage: str = "UTF-8"
    printer_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    poll_interval_seconds: float = Field(default=2.0, ge=0.25, le=60)
    api_timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    @model_validator(mode="after")
    def unique_printers(self) -> "Settings":
        if len({printer.name for printer in self.printers}) != len(self.printers):
            raise ValueError("Los nombres de impresora no pueden repetirse")
        if len({printer.ip for printer in self.printers}) != len(self.printers):
            raise ValueError("Cada impresora debe tener una IP diferente")
        return self

    def normalized_api_url(self) -> str:
        return self.system_api_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

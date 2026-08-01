from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    system_api_url: str = Field(min_length=8)
    print_agent_api_key: SecretStr
    print_agent_id: str = Field(default="xp470l-01", pattern=r"^[a-zA-Z0-9._-]{1,64}$")

    printer_host: str = Field(min_length=1)
    printer_port: int = Field(default=9100, ge=1, le=65535)
    printer_dpi: int = Field(default=203, ge=100, le=600)
    printer_encoding: str = "utf-8"
    printer_codepage: str = "UTF-8"
    printer_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    poll_interval_seconds: float = Field(default=2.0, ge=0.25, le=60)
    api_timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    def normalized_api_url(self) -> str:
        return self.system_api_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

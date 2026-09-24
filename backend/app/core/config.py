from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://market_ai:market_ai@localhost:5432/market_ai"
    massive_api_key: SecretStr = Field(default=SecretStr(""))
    massive_base_url: str = "https://api.massive.com"
    massive_timeout_seconds: float = 15.0
    massive_max_retries: int = 3
    massive_retry_base_seconds: float = 0.25
    provider_data_delay_minutes: int = Field(default=180, ge=0)
    ingestion_concurrency: int = Field(default=2, ge=1, le=20)

    alpaca_api_key: SecretStr = Field(default=SecretStr(""))
    alpaca_secret_key: SecretStr = Field(default=SecretStr(""))
    openai_api_key: SecretStr = Field(default=SecretStr(""))


@lru_cache
def get_settings() -> Settings:
    return Settings()

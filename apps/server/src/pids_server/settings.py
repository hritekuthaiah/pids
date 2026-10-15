"""Typed runtime configuration, read from the environment (and ``.env`` in dev)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    env: Literal["dev", "test", "prod"] = Field(default="dev", alias="PIDS_ENV")
    log_level: str = Field(default="INFO", alias="PIDS_LOG_LEVEL")

    postgres_user: str = "pids"
    postgres_password: SecretStr
    postgres_db: str = "pids"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_password: SecretStr
    redis_host: str = "localhost"
    redis_port: int = 6379

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_server_user: str = "pids-server"
    mqtt_server_password: SecretStr

    jwt_secret: SecretStr
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    site_config: Path = Field(
        default=Path("config/sites/site-alpha.yaml"), alias="PIDS_SITE_CONFIG"
    )
    decision_model: Path = Field(
        default=Path("config/models/decision-model.json"), alias="PIDS_DECISION_MODEL"
    )
    anomaly_model: Path = Field(
        default=Path("ml/artifacts/anomaly-iforest.joblib"), alias="PIDS_ANOMALY_MODEL"
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"], alias="PIDS_CORS_ORIGINS"
    )

    decision_tick_hz: float = 5.0
    live_publish_hz: float = 2.0
    observation_hz: float = 1.0
    metrics_port_decision: int = 9101
    metrics_port_worker: int = 9102

    expo_access_token: SecretStr | None = None

    @property
    def database_url(self) -> str:
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        pw = self.redis_password.get_secret_value()
        return f"redis://:{pw}@{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # populated from the environment / .env

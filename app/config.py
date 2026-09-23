"""
Application configuration loaded from environment variables.
Uses pydantic-settings for validation and type coercion.
"""
import logging
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+psycopg://user:pass@localhost:5432/db"

    # Vapi shared secret for x-vapi-secret header validation
    vapi_shared_secret: Optional[str] = None

    # Optional API key for write operations on REST API
    api_key: Optional[str] = None

    # Logging
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def configure_logging(settings: Settings) -> None:
    """Configure structured logging to stdout."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

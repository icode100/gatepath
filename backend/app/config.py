from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GATE 2027 Prep API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "sqlite+aiosqlite:///./gate_prep.db"
    auto_create_db: bool = True
    seed_data: bool = True
    sql_echo: bool = False

    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def async_database_url(self) -> str:
        """Normalize common deployment URLs for SQLAlchemy's async drivers."""
        url = self.database_url
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def allowed_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",")]
        return [origin for origin in origins if origin]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

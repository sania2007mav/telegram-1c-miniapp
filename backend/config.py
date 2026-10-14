from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    app_url: str = "https://pocket.melnichuk.kz"
    api_public_url: str = "https://pocket.melnichuk.kz/api"
    credentials_encryption_key: str = ""
    database_path: str = str(Path(__file__).resolve().parent.parent / "data" / "app.db")
    host: str = "127.0.0.1"
    port: int = 8110


settings = Settings()

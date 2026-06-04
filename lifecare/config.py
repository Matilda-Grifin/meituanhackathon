from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_dotenv_files() -> None:
    """优先加载子项目 .env，再加载上级黑客松目录 .env（与现有习惯兼容）。"""
    pkg_root = Path(__file__).resolve().parent.parent
    hackathon_root = pkg_root.parent
    load_dotenv(pkg_root / ".env")
    load_dotenv(hackathon_root / ".env")


_load_dotenv_files()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    amap_key: str = Field(default="", validation_alias="AMAP_KEY")
    default_city: str = Field(default="杭州", validation_alias="DEFAULT_CITY")
    default_lng: float = Field(default=120.153576, validation_alias="DEFAULT_LNG")
    default_lat: float = Field(default=30.266863, validation_alias="DEFAULT_LAT")
    mock_sandbox_base_url: str = Field(
        default="http://127.0.0.1:9000", validation_alias="MOCK_SANDBOX_BASE_URL"
    )
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    use_open_meteo: bool = Field(default=True, validation_alias="USE_OPEN_METEO")


def get_settings() -> Settings:
    return Settings()

from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量读取配置；生产环境通过平台注入 DATABASE_URL。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 完整连接串，例如 postgresql://user:pass@host:5432/dbname
    database_url: Optional[str] = None

    @field_validator("database_url", mode="before")
    @classmethod
    def strip_database_url(cls, v: Any) -> Any:
        """去掉首尾空白，避免复制连接串时带入换行导致 DNS 解析失败。"""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()

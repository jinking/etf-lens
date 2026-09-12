from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: str = "dev"
    database_path: Path = Path("data/warehouse/etf.duckdb")
    raw_path: Path = Path("data/raw")
    export_path: Path = Path("data/exports")
    log_level: str = "INFO"
    timezone: str = "Asia/Shanghai"
    hithink_finance_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ETF_",
        extra="ignore",
    )


settings = Settings()

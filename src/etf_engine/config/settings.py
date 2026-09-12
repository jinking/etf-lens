from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: str = "dev"
    database_path: Path = Path("data/warehouse/etf.duckdb")
    raw_path: Path = Path("data/raw")
    export_path: Path = Path("data/exports")
    log_level: str = "INFO"
    timezone: str = "Asia/Shanghai"
    #: 收盘后份额/净值数据通常的发布时点；早于该时点运行时 as-of 回退到上一交易日。
    market_data_ready_hour: int = 17
    hithink_finance_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ETF_",
        extra="ignore",
    )


settings = Settings()

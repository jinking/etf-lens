from datetime import date
from pathlib import Path

import pandas as pd


class RawSnapshotStore:
    def __init__(self, base_path: Path):
        self.base_path = base_path

    def write_records(
        self,
        *,
        source: str,
        dataset: str,
        trade_date: date,
        records: list[dict],
    ) -> Path:
        target = (
            self.base_path
            / f"source={source}"
            / f"dataset={dataset}"
            / f"date={trade_date.isoformat()}"
        )
        target.mkdir(parents=True, exist_ok=True)
        path = target / "part-000.parquet"
        pd.DataFrame(records).to_parquet(path, index=False)
        return path

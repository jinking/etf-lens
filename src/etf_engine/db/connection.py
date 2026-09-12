from pathlib import Path

import duckdb


def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))

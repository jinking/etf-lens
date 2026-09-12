from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for path in (
    ROOT / "data/raw",
    ROOT / "data/warehouse",
    ROOT / "data/exports",
    ROOT / "data/backups",
):
    path.mkdir(parents=True, exist_ok=True)
    keep = path / ".gitkeep"
    keep.touch(exist_ok=True)

print("Project data directories initialized.")
print("Next:")
print('  1. pip install -e ".[dev]"')
print("  2. etf db-init")
print("  3. etf doctor")

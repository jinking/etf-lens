.PHONY: install bootstrap test lint format api doctor clean

install:
	python -m pip install -e ".[dev]"

bootstrap:
	python scripts/bootstrap.py

test:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check --fix src tests

api:
	etf api

doctor:
	etf doctor

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov

.PHONY: check lint fmt types

check: lint fmt types ## Everything a change must pass before it is pushed

lint:
	uv run ruff check .

fmt:
	uv run ruff format --check .

types:
	uv run mypy

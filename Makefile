.PHONY: check lint fmt imports types test

check: lint fmt imports types test ## Everything a change must pass before it is pushed

lint:
	uv run ruff check .

fmt:
	uv run ruff format --check .

imports:
	uv run lint-imports

types:
	uv run mypy

test:
	uv run pytest

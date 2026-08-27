.PHONY: format lint typecheck test test-integration check

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src tests

test:
	uv run pytest tests/unit tests/regression

test-integration:
	uv run pytest tests/integration

check: lint typecheck test

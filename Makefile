.PHONY: install test lint fmt typecheck clean

install:
	poetry install

test:
	poetry run pytest tests/ -v

lint:
	poetry run ruff check .

fmt:
	poetry run black . && poetry run ruff check --fix .

typecheck:
	poetry run mypy declaw/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true

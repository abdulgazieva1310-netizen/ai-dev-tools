Documents

- `docs/process.md` - how work is organized
- Before writing tests, read `docs/testing-guidelines.md`
- For anything touching the UI, read `docs/design-system.md`

Commands

- `uv sync` — install dependencies
- `uv run ruff check .` — lint Python files
- `uv run ruff format --check .` — check Python formatting
- `uv run pytest` — run the whole suite
- `uv run pytest tests/test_home.py` — run one test file

Rules

- Add dependencies in `pyproject.toml`. Do not add a dependency without asking first.

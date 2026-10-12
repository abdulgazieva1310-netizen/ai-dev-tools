# SkillSwap

## Development setup

Install the project and its dependencies from a fresh checkout with:

```sh
uv sync
```

Run the development server at <http://127.0.0.1:8000/> with:

```sh
uv run python manage.py runserver
```

Run the home page test or the full test suite with:

```sh
uv run pytest tests/test_home.py
uv run pytest
```

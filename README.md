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

## Docker Compose development environment

Copy the example environment file and start the Django and PostgreSQL services:

```sh
cp .env.example .env
docker compose config
docker compose up --build -d
```

Wait until both services are healthy, then apply Django migrations:

```sh
docker compose ps
docker compose exec web python manage.py migrate
```

The home page is available at <http://127.0.0.1:8000/>. Inspect service health and logs with:

```sh
docker compose ps
docker compose logs
```

Restart the services with `docker compose restart`. PostgreSQL uses the named `postgres_data` volume, so its data survives container restarts. Stop the services with:

```sh
docker compose down
```

The `.env` file is local and ignored by Git. Use `.env.example` as the starting point; its values are for local development only.

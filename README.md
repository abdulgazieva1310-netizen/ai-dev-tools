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

## Account identity

`accounts.User` is the project's custom user model. It uses a unique, lowercased and trimmed email address for login, Django password hashing,
an optional `email_verified_at` timestamp, and one of four states: `active`, `suspended`, `deletion_pending`, or `deleted`. Only `active`
accounts can authenticate.

The user model is configured as `AUTH_USER_MODEL` and defined in `accounts/0001_initial.py`. Keep it in the account app's initial migration
before creating initial migrations for other project apps; Django apps that reference users must depend on the swappable user model. For a
fresh local database, apply migrations with `uv run python manage.py migrate` (or `docker compose exec web python manage.py migrate`).

## Google sign-in

Create an OAuth client in Google Cloud and set `GOOGLE_OIDC_CLIENT_ID`,
`GOOGLE_OIDC_CLIENT_SECRET`, and `GOOGLE_OIDC_CALLBACK_URL` in your local `.env`.
Register the same callback URL with Google. For local development, use
`http://localhost:8000/oidc/callback/`. Never commit real credentials.

The app uses Google OpenID Connect at `/google/login/`; signed-in users can
explicitly link an identity at `/google/link/`. The external identity table keeps
Google's stable subject identifier. Account matching by email does not link identities.

## Profiles

An active signed-in account can create one profile at `/profile/new/`. The owner
can edit privacy, biography, language labels, projects, certificates, and teaching
or learning skills from the profile page. Profile URLs use opaque numeric IDs at
`/profiles/<id>/`; server-side visibility checks return 404 when a viewer lacks
access. Apply the profile schema with `uv run python manage.py migrate`.

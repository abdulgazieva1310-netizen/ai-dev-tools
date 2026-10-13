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

## Frontend assets

The responsive page shell (`templates/base.html`) is styled with Tailwind CSS
and served through Django static files. Frontend source lives in `frontend/`
and is built to `static/build/` with Vite. `node_modules/` and `static/build/`
are build artifacts and are gitignored; `package.json` and `package-lock.json`
are committed.

Install the frontend toolchain from the lockfile (use `npm install` instead of
`npm ci` when you change `package.json`):

```sh
npm ci
```

Build the hashed stylesheet, module script, and Vite manifest into
`static/build/`:

```sh
npm run build
```

Run the Vite dev server with hot reload at <http://localhost:5173/>. Set
`VITE_DEV_SERVER_URL=http://localhost:5173` in your environment so Django
templates load modules from the dev server; leave it unset to use the built
manifest:

```sh
npm run dev
```

In production, collect the built assets (and everything else in `static/`)
into `STATIC_ROOT` and serve them with Django or a web server:

```sh
uv run python manage.py collectstatic --noinput
```

The `{% vite_asset %}` template tag renders the stylesheet and module script
tags from the manifest, or the dev-server tags when `VITE_DEV_SERVER_URL` is
set. If no manifest exists and no dev server is configured, it renders nothing
so pages keep working.

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

## Skill categories and live lessons

Staff can manage seeded skill categories in Django Admin and assign shared skills
to them there. Profile owners can create shared skills without a category. Active,
verified members can create lesson drafts at `/lessons/` and submit complete lessons
for staff review. Staff publish or reject pending lessons in Django Admin. Only
published lessons appear to learners, and profile visibility rules also apply to
lesson details. Apply the listings schema with `uv run python manage.py migrate`.

## Listing search tests

The regular SQLite suite is `uv run pytest`. PostgreSQL full-text matching and
ranking require the Compose database. From a fresh checkout, run these exact
commands to start it, apply migrations, and run PostgreSQL-specific search
assertions (which fail if the PostgreSQL run is misconfigured to use SQLite):

```sh
cp .env.example .env
docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web pytest tests/test_listing_search.py
```

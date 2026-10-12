# Background jobs

Durable background work runs through PostgreSQL and Django only. There is no
Celery, no Redis and no external queue: `jobs.BackgroundJob` rows are the queue,
and `python manage.py run_jobs` is the worker.

## Running the worker

### Docker Compose

`compose.yaml` defines a `worker` service that runs the same image as `web`,
waits for a healthy `db`, and restarts if it exits:

```bash
docker compose up -d db worker          # start the worker
docker compose logs -f worker           # tail the worker log
docker compose stop worker              # SIGTERM stops the worker after the
                                        # current cycle
docker compose restart worker           # apply new code or new migrations
```

Run one cycle by hand (useful when checking a queue is draining):

```bash
docker compose exec web python manage.py run_jobs --run-now
```

### Locally

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py run_jobs                 # poll loop
uv run python manage.py run_jobs --run-now       # single iteration, then exit
uv run python manage.py run_jobs --poll-interval 1 --batch-size 50
```

Locally the project falls back to SQLite when `DB_HOST` is unset. The row
locking used by the claim path (`SELECT ... FOR UPDATE SKIP LOCKED`) is only
meaningful on PostgreSQL, so run the worker against the Compose database.

## Command options

| Option | Default | Meaning |
| --- | --- | --- |
| `--run-now` | off | Claim one batch, run the handlers, exit. |
| `--poll-interval` | `BACKGROUND_JOB_POLL_INTERVAL` (5s) | Sleep between empty cycles. |
| `--batch-size` | `BACKGROUND_JOB_BATCH_SIZE` (10) | Maximum jobs claimed per cycle. |

## How a job runs

1. A caller enqueues the job **inside the transaction that needs the work**:
   `jobs.enqueue.enqueue(job_type, payload, idempotency_key=...)`. If that
   transaction rolls back, the job disappears with it.
2. Repeated enqueues with the same `idempotency_key` return the existing job
   instead of creating a second one or raising `IntegrityError`. Omitting the
   key derives a deterministic one from `(job_type, scope, payload)`.
3. `claim_due_jobs()` selects, inside a single `transaction.atomic()` block,
   jobs that are PENDING and due **or** RUNNING with an expired lease, taking
   them with `SELECT ... FOR UPDATE SKIP LOCKED`.
4. Each claimed job gets `status = running`, an incremented `attempt_count` and
   a `lease_expiry`. That lease is **committed before the handler runs**, so a
   worker that dies mid-handler leaves a reclaimable lease instead of holding an
   open row lock.
5. The handler runs outside the claim transaction. On success the job becomes
   `success`; on failure the job is rescheduled or fails permanently (below).
6. A job whose lease expired (worker crash) is reclaimed by the next worker and
   retried. A job with a **live** lease is never claimed, so two workers cannot
   run it at the same time.

## Retries and backoff

Each claim counts as one attempt. After a handler raises:

- if `attempt_count >= BACKGROUND_JOB_MAX_ATTEMPTS` (default `5`), the job
  becomes `permanent_failure` and is never claimed again;
- otherwise the job returns to `pending` with
  `run_after = now + backoff(attempt)`, where backoff is exponential
  `30s, 60s, 120s, 240s...` capped at `BACKGROUND_JOB_BACKOFF_MAX_SECONDS`
  (`3600`). The job is therefore not re-claimed immediately.

A job whose `job_type` has no registered handler fails permanently on its first
attempt, because retrying cannot help.

## Registering a job type and a handler

Job types are allowlisted in `jobs/job_types.py`. Registering a handler with
`jobs.handlers.register_handler` registers the type at the same time, so a type
without a handler can never be stored or enqueued.

```python
from jobs.handlers import register_handler


@register_handler("listing_transcribed")
def handle_listing_transcribed(payload):
    listing_id = payload["listing_id"]  # references only
    ...
```

Handlers must be idempotent: a crash after the handler's own writes but before
`success` is recorded will replay the job.

## Payloads and error summaries

`jobs.sanitize` keeps stored data small and non-sensitive:

- payloads must be a mapping of record references, at most 4 KiB encoded, at
  most 3 levels deep, with string values of at most 200 characters;
- keys that look sensitive (`password`, `token`, `secret`, `authorization`, …)
  are rejected outright, and `bytes`/media are never accepted;
- error summaries are redacted (secret-looking values become `[redacted]`),
  whitespace-collapsed and capped at 200 characters, in the database, in the
  worker log and in the admin.

## Configuration

| Setting | Environment variable | Default |
| --- | --- | --- |
| `BACKGROUND_JOB_MAX_ATTEMPTS` | `BACKGROUND_JOB_MAX_ATTEMPTS` | `5` |
| `BACKGROUND_JOB_LEASE_SECONDS` | `BACKGROUND_JOB_LEASE_SECONDS` | `60` |
| `BACKGROUND_JOB_BACKOFF_BASE_SECONDS` | `BACKGROUND_JOB_BACKOFF_BASE_SECONDS` | `30` |
| `BACKGROUND_JOB_BACKOFF_MAX_SECONDS` | `BACKGROUND_JOB_BACKOFF_MAX_SECONDS` | `3600` |
| `BACKGROUND_JOB_POLL_INTERVAL` | `BACKGROUND_JOB_POLL_INTERVAL` | `5` |
| `BACKGROUND_JOB_BATCH_SIZE` | `BACKGROUND_JOB_BATCH_SIZE` | `10` |

Keep `BACKGROUND_JOB_LEASE_SECONDS` comfortably longer than the slowest handler;
a lease that expires while a handler is still running lets a second worker pick
the same job up.

## Tests

```bash
uv run pytest                                     # SQLite: everything but the
                                                  # PostgreSQL-only job tests
docker compose exec web pytest tests/test_background_jobs.py   # PostgreSQL
```

The lock-sensitive tests (`concurrent enqueue`, `competing workers`,
`skip locked rows`) call `pytest.fail()` when they are run on SQLite, because
SQLite ignores `SKIP LOCKED` and would let them pass for the wrong reason.
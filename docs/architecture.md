# SkillSwap — MVP Technical Architecture

**Status:** Proposed architecture based on selected Option 2  
**Selected stack:** Django, PostgreSQL, Django templates, HTMX, Alpine.js, Tailwind CSS, one React island built with Vite, PostgreSQL-backed background jobs, and Docker Compose

## 1. Architecture goals

- Ship one responsive web application for the complete teach-and-learn exchange.
- Keep points, bookings, permissions, and content access authoritative on the server.
- Use PostgreSQL transactions for workflows that move points or change access.
- Start as a modular Django monolith, with one isolated React island for the retro board.
- Process submitted recordings for transcription, then discard the recording rather than retaining uploaded media.
- Run the complete application stack through Docker Compose.

## 2. System shape

```text
Browser
  │ HTTP/HTTPS
  ▼
Django web application ───────── PostgreSQL
  │   ├─ templates + HTMX + Alpine.js + Tailwind CSS
  │   ├─ Vite-built React bundle for the retro board
  │   ├─ transient recording upload and processing
  │   └─ OpenAI API (Whisper transcription and LLM features)
  │
  ├──────── PostgreSQL-backed job table
  │
  └─ Docker Compose worker process
      ├─ transcription and LLM jobs
      ├─ email and notification delivery
      └─ booking reminders and expiry checks
```

The browser talks to Django. Django owns authentication, authorization, business rules, and integration with OpenAI. PostgreSQL is the source of truth for product data and queued job state. There is no Redis broker and no persistent media object store. Recordings are held only in temporary processing storage and deleted after processing, including on failure and timeout paths.

## 3. Application structure and frontend

Keep one Django project divided into focused apps. Each app owns its models, services, and views. Cross-app state changes go through service functions inside database transactions.

- **`accounts`** — custom user model, email verification, Google sign-in integration, account state, deletion workflow.
- **`profiles`** — public profile, languages, skills taught and wanted, projects, certificates, follows, profile visibility.
- **`catalog`** — categories, live lesson listings, recording/transcription metadata, outcomes, level, duration, price, publication and moderation state.
- **`library`** — learner access entitlements and completion history. No uploaded media is retained as a library asset.
- **`points`** — point accounts, immutable ledger entries, holds/reservations, and transactional services for grants, reservations, captures, and refunds.
- **`scheduling`** — teacher availability, time slots, bookings, cancellation and attendance/completion states.
- **`communications`** — private conversations and messages, in-app notifications, email preferences.
- **`trust`** — reviews, reports, blocks, and moderation decisions.
- **`operations`** — admin-facing dispute and moderation workflows, background job records, and audit events.
- **`transcription`** — transient recording intake, OpenAI transcription calls, transcript persistence, and recording deletion lifecycle.

### User interface

- Render the main interface with Django templates and Tailwind CSS.
- Use HTMX for server-rendered partial updates such as search/filter results, booking actions, and message refreshes.
- Use Alpine.js for small client-side interactions such as menus, dialogs, and toggles.
- Mount the retro board as a single React island in one Django template. Build that island and its assets with Vite; it is not a separate frontend application and does not own backend business logic.
- Keep Django endpoints and server-side authorization authoritative for all UI interactions, including the React island.

## 4. Data model

Use PostgreSQL with Django migrations. Use opaque UUIDs for externally addressable records, UTC timestamps, and integer point amounts.

### Identity and discovery

- `User`: email login identifier, password hash when applicable, verification state, active/suspended/deletion state, created timestamp.
- `ExternalIdentity`: provider and provider subject for Google sign-in, linked to a user.
- `Profile`: user, display name, bio, languages, visibility settings.
- `Skill`, `Category`, `UserSkill`: normalized skill/category catalog and the user's teach/learn interests and self-reported level.
- `Project` and `Certificate`: optional profile items.
- `Follow`: follower and followed profile, unique pair.
- `Listing`: owner, type (`live` or `transcription`), title, description, outcomes, category/skill, level, duration where relevant, point price/reward, transcript/preview metadata, publication and moderation state.

### Transcription and learner library

- `TranscriptionJob`: requesting user, listing or draft reference, status, provider/model, requested options, attempt count, timestamps, failure category, and idempotency key. Do not store raw recording bytes or a durable upload path in this row.
- `Transcript`: resulting text, language and processing metadata, associated listing/job, review/publication state. Apply retention and deletion controls to transcript text.
- `TranscriptAccess`: learner, listing/transcript, point ledger reference, created timestamp; unique learner/listing pair where paid unlocks are used.
- `LearningProgress`: learner, listing, completion state and timestamps.

The product plan originally describes downloadable PDFs, presentations, videos, and exercises. With the selected no-file-storage requirement, those uploaded assets cannot be retained or unlocked as downloadable resources. The MVP content flow here is recording-to-transcript. If retained downloadable materials remain required, that requirement needs a separate storage decision.

### Points

- `PointAccount`: user and cached available/reserved totals. The ledger remains authoritative.
- `PointTransaction`: immutable record with account, signed amount, type, related booking/unlock/admin action, idempotency key, actor, timestamp, and optional reason.
- `PointReservation`: booking, learner account, amount, state (`reserved`, `captured`, `released`), and timestamps.

A reservation changes totals atomically and records ledger entries. Capturing transfers the reserved amount from learner to teacher in one transaction; releasing returns it. Use database constraints for unique idempotency keys and valid nonnegative balances. Never edit or delete posted transactions; correct mistakes with a compensating transaction and audit reason.

### Scheduling, messaging, and trust

- `AvailabilityRule` and `AvailabilityException`: teacher's recurring availability and date-specific changes, stored with an explicit timezone.
- `Booking`: listing, teacher, learner, UTC start/end, display timezone, meeting URL, status, cancellation actor/reason, and confirmation timestamps.
- `Conversation` and `Message`: private participants and text messages, with participant checks on every read/write.
- `Review`: booking, author, recipient, rating, text, moderation state; one review per participant per completed booking.
- `Report`, `Block`, and `ModerationAction`: reporter/subject or content, reason, status, assigned admin, decision, and audit history.
- `Notification`: recipient, type, payload/reference, read and delivery state, created timestamp.
- `BackgroundJob`: job type, JSON payload, status, attempts, run-after time, lease/lock fields, error summary, and timestamps.
- `AuditEvent`: actor, action, target, timestamp, and structured details for administrative and sensitive workflow changes.

Add indexes for listing filters, teacher availability, booking participant/time/status, unread messages/notifications, ledger account/time, and runnable jobs. Start with PostgreSQL full-text search and indexed filters; defer a separate search service.

## 5. Core workflows and transaction boundaries

All steps that affect points, access, or booking state run in server-side service functions using `transaction.atomic()`. Lock relevant account and booking rows with `select_for_update()` and use idempotency keys so retries cannot issue or spend points twice.

### Background job mechanism

Use a small PostgreSQL-backed queue implemented with `BackgroundJob` and a Django management command (for example, `python manage.py run_jobs`). Enqueue job rows in the same database transaction as the action that requires them. A worker claims due rows in short transactions using `select_for_update(skip_locked=True)`, sets a lease, performs the task outside the claim transaction, then marks it complete or schedules a bounded retry. Jobs must be idempotent. Expired leases are reclaimed after worker crashes. Run web and worker as separate services from the same image in Docker Compose. A management command invoked by Compose on a fixed interval can handle periodic reminders and expiry scans; no Celery or Redis is required.

This is suitable for modest MVP throughput and avoids a separate broker. Keep job payloads small and store references to database records, not recordings or secrets. Monitor failed and repeatedly retried jobs through Django Admin/operations views.

### Starter points and earned points

- On verified account creation, create the point account and one starter-grant transaction in the same transaction (initial proposed grant: 20 points, subject to product confirmation).
- On a completed eligible live booking, create the teacher reward exactly once (initial proposed reward: 10 points). A unique source reference/idempotency key prevents duplicate awards.
- Admin adjustments require a reason and create ledger entries plus an audit event.

### Recording transcription

1. Django validates the authenticated user's permission, request size, allowed audio type, and rate limits before accepting a recording.
2. Stream the recording to a size-limited temporary directory or in-memory temporary file. Do not place it in a persistent media directory, database, or durable volume.
3. Create a `TranscriptionJob` and corresponding `BackgroundJob` row transactionally. The worker reads the temporary recording, sends it to OpenAI Whisper transcription, persists the transcript and provider metadata, and removes the temporary file in a `finally` cleanup path.
4. If the web process and worker are separate containers, use a short-lived, access-restricted temporary shared volume only for the job handoff. Store opaque job-scoped paths, impose strict TTL/size limits, and delete after success, failure, or expiry. Do not back this volume up. For a single-process synchronous deployment, avoid the shared volume and process directly.
5. On provider or worker failure, remove the temporary bytes and mark the job failed/retryable. A retry requires a fresh recording unless the deployment explicitly keeps a short-lived transient handoff copy until retry expiry.
6. Persist transcript text only according to the product's retention and user-consent policy. Do not use the recording itself to train models. Do not log recording contents or transcript text by default.

OpenAI model names and API features are configuration, not hard-coded architecture assumptions. Send only the data needed for the requested transcription or LLM task; handle API keys as secrets. Any LLM output that affects user-visible content should be clearly attributable and reviewed/edited by the user where appropriate. Keep point, booking, moderation, and authorization decisions deterministic application logic rather than delegating them to an LLM.

### Transcript access

1. Confirm the transcript/listing is published and the learner is not the creator.
2. In one transaction, lock the learner's point account, check the available balance, record the debit and creator credit, and create the unique access entitlement.
3. A repeated request returns the existing entitlement without another charge.
4. Serve transcript text only after an entitlement and visibility check. No media download or permanent file URL exists.

### Live booking and completion

1. A learner selects a published listing and open slot. Recheck availability on submit to prevent double booking.
2. In one transaction, lock the slot/booking and learner point account, create the booking, reserve its point cost, and persist notification/job intent.
3. Reveal the meeting URL only to the two booking participants according to booking status and configured release time.
4. Participants confirm completion. After both confirmations, atomically capture the learner's reservation to the teacher and mark the booking complete. Enable reviews only after completion.
5. If a participant disputes completion, transition the booking to `disputed`, keep the reservation held, and create an admin case. Admin resolution captures or releases the hold and records the decision.
6. A scheduled job identifies overdue unconfirmed bookings and applies an explicit response deadline/escalation policy. The unresolved policy in `plan.md` must be decided before launch; the worker must not silently capture or refund by default.

### Cancellation and no-show

Represent cancellation, late cancellation, and no-show outcomes as explicit booking state transitions with corresponding hold capture/release rules. Record who initiated the action and when. The free-cancellation deadline, late-cancellation consequences, no-show evidence, and response deadline remain product decisions in `plan.md`; implement these rules only after agreement.

## 6. Authentication, authorization, and privacy

- Use a supported Django authentication integration for Google OAuth; require verified email before publishing listings or exchanging booking links.
- Use Django CSRF protection, secure password hashing, production session cookies marked `Secure` and `HttpOnly`, and appropriate `SameSite` settings.
- Enforce object-level authorization in querysets and service methods, not only by hiding UI controls. Test permissions for profiles, messages, bookings, reports, transcripts, and job status.
- Keep meeting URLs and private profile fields out of public responses, logs, and notifications visible to other users.
- Accept only configured audio formats and enforce upload size, duration, and request time limits. Use generated temporary filenames; never trust client filenames as paths. Clean temporary files after every processing outcome and with a periodic stale-file cleanup command.
- Add throttling for login, messaging, transcription/LLM requests, reports, and other abuse-prone endpoints. Escape/render user content safely and apply a restrictive Content Security Policy where practical.
- Account deletion should remove or anonymize profile, transcript, and message data according to policy while retaining the minimum transaction and dispute records required by retention rules.

## 7. Media processing and OpenAI integration

There is no durable file storage service. Recordings are accepted only for processing and discarded after the task; enforce a maximum size and duration to bound temporary disk use and API cost. Use `ffmpeg` in the application/worker image to inspect and convert supported inputs and extract audio where the source contains video. Run ffmpeg with argument arrays (never shell interpolation), resource/time limits, and generated temporary paths. Remove source and derived audio files in all exit paths.

Send extracted audio to OpenAI Whisper for transcription. Use OpenAI's LLM API for explicitly scoped text features such as transcript cleanup, summaries, or suggested learning outcomes. Persist only selected outputs and metadata; make any transcript-derived content reviewable. Keep API calls in background jobs when they may exceed a normal web request, with bounded retries and provider timeout handling. Avoid logging prompts, transcripts, or credentials by default.

## 8. Notifications and scheduled work

Persist in-app notifications in PostgreSQL. Create durable `BackgroundJob` rows for email delivery and reminders in the same transaction as the event that requires notification. The worker retries transient provider failures with bounded backoff and an idempotency key. Periodic management commands enqueue upcoming-session reminders, stale confirmation checks, expired job cleanup, and temporary-file cleanup. Respect user email preferences for non-essential notifications.

## 9. Deployment and operations

Use Docker Compose as the deployment and local orchestration mechanism. The Compose file defines the Django web service, PostgreSQL, and a Django management-command worker using the same application image. Include a one-shot migration service/command for controlled releases. Do not include Celery, Redis, a cloud file-storage service, or a separate hosting platform in the architecture.

- Use environment-specific Compose configuration and `.env` inputs for local development; inject production secrets through the host's secret mechanism rather than committing them.
- For production, mount PostgreSQL data on a persistent volume and establish database backups. Mount only an ephemeral, size-limited temporary volume for media handoff if separate web and worker containers require it; exclude it from backups and ensure cleanup.
- Terminate TLS at the deployment host or reverse proxy in front of Compose. Configure Django allowed hosts, trusted origins, secure cookies, and debug mode appropriately.
- Run schema migrations as a controlled release step before serving the new version.
- Send structured logs and exception reports to the configured logging destination. Track job age/failures, transcription and LLM provider errors, booking completion/dispute rates, point-ledger reconciliation, temporary disk use, and email delivery failures.
- Provide a management command that compares cached point totals with ledger-derived totals and reports mismatches; repair through audited transactions, not direct balance edits.
- Add health checks for web, database, and worker readiness. OpenAI or email outages must not corrupt committed bookings or point transactions.

## 10. Search and recommendations

Use PostgreSQL full-text search for listing titles, descriptions, and published transcript text, with structured filters for category, level, format, language, rating, and point price. Begin recommendations as a query/ranking service using stated learning interests, skill level, language, followed teachers, and listing attributes. Include discovery opportunities for newer teachers rather than ranking only by popularity. Keep ranking rules behind a service boundary; LLM recommendations are not required for the MVP.

## 11. Testing and code quality

- Use `pytest` and `pytest-django` for model, view, permission, service, and workflow tests.
- Test point and booking concurrency/idempotency against PostgreSQL, since SQLite does not provide equivalent locking behavior.
- Mock OpenAI API calls in normal test runs. Cover ffmpeg invocation, temporary file cleanup, provider failures, job retries, and transcript access controls.
- Use Ruff for Python linting and formatting. Run it in the developer workflow and CI.
- Build the Vite React island and verify Django serves the generated manifest/assets in production mode.

## 12. MVP build sequence

1. Establish the Docker Compose project, Django settings, PostgreSQL, custom user model, email verification, Google sign-in, pytest-django, and Ruff.
2. Build the Django template foundation with Tailwind, HTMX, and Alpine.js; add the Vite-built React retro-board island.
3. Build profiles, skills, listings, PostgreSQL search, and the PostgreSQL-backed background-job worker.
4. Implement the point ledger, transcript entitlement, and recording-to-Whisper flow with ffmpeg and temporary-file cleanup.
5. Implement availability, booking reservation, completion, cancellation states, dispute admin workflow, and reminders.
6. Add messaging, reviews, notifications, reports, blocks, moderation, LLM text features, monitoring, and reconciliation.

Before launch, settle the policy choices identified in `plan.md`: point issuance values and safeguards; completion response deadline; cancellation and no-show rules; audio size/duration limits and supported formats; moderation ownership and response times; privacy, transcript retention/deletion, consent, and content ownership. The planned no-file-storage approach also requires reconciling the original plan's promise of retained downloadable learning materials with the recording-to-transcript-only flow.

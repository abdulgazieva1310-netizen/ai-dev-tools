 ## 1. Scaffold the empty Django project with a passing home test

  ## Goal

  Create the smallest runnable Django project for SkillSwap, with a home page and a passing test, so later work has a verified starting point.

  ## Acceptance criteria

  ☐ Initialize the Python project with uv and configure Django using only dependencies approved before they are added.
  ☐ Add a Django / route that returns a simple HTML response, and add tests/test_home.py asserting HTTP 200 and expected page content.
  ☐ Document the fresh-checkout setup and test commands; uv sync, uv run pytest tests/test_home.py, and uv run pytest pass.

  ## Out of scope

  • Docker Compose and PostgreSQL setup are in task #2; Ruff configuration is in task #3.
  • The custom user model and authentication flows are in tasks #4–#7; product models and frontend features are covered by later backlog tasks.

  ## Constraints

  • Keep changes to pyproject.toml, uv.lock, manage.py, the Django project package, tests/test_home.py, and the setup instructions in README.md.

  • Use Django and pytest with pytest-django; request approval before adding these or any other dependencies, and declare approved dependencies in
    pyproject.toml as required by AGENTS.md.

  • Do not configure a database, create models, or implement SkillSwap product behavior in this task.


 ## 2. Run the Django app and PostgreSQL locally with Docker Compose

  ## Goal

  Run the Django home page and PostgreSQL together through a repeatable local Docker Compose workflow, with database data preserved when containers restart.

  ## Acceptance criteria

  ☐ Add a Docker image and Compose configuration for the Django web service and PostgreSQL only; the web service waits for PostgreSQL's health check before
    starting.

  ☐ Configure the Django database connection from environment variables and provide a non-secret .env.example; ensure real .env values are not committed.

  ☐ Document commands to configure the local environment, build/start the services, apply Django migrations, check service health/logs, restart services,
    and stop them.

  ☐ Verify docker compose config succeeds, the web service returns HTTP 200 at /, migrations complete, and PostgreSQL data remains after the database
    container is restarted.

  ## Out of scope

  • The empty Django project and home test are in task #1; Ruff setup is in task #3.
  • The PostgreSQL-backed background worker is in task #12; account/authentication and product features are in later tasks.
  • Production backup/restore and operating procedures are in task #38; do not add a separate hosting platform, Celery, Redis, or file storage.

  ## Constraints

  • Keep changes to the Dockerfile, Compose configuration, .dockerignore, .env.example, .gitignore, pyproject.toml/uv.lock if needed, Django database
    settings, and setup instructions in README.md.

  • Use the existing Django project and uv workflow; request approval before adding a PostgreSQL driver or any other dependency, and declare approved
    dependencies in pyproject.toml as required by AGENTS.md.

  • Use a named persistent PostgreSQL volume and non-secret example values; never place real credentials in tracked files.

  ## 3. Configure Ruff linting and formatting

  ## Goal

  Give contributors and pull requests the same repeatable Ruff lint and format checks for the Django project's Python code.

  ## Acceptance criteria

  ☐ Request approval before adding Ruff; after approval, declare it as a development dependency in pyproject.toml and update uv.lock.

  ☐ Configure Ruff in pyproject.toml to use the project's declared Python target and a documented rule set; resolve Ruff findings in the current scaffold
    without unrelated refactoring.

  ☐ Add uv run ruff check . and uv run ruff format --check . to the developer commands in AGENTS.md and run both successfully.

  ☐ Add or update GitHub Actions so pull requests run uv sync --locked, both Ruff checks, and uv run pytest; confirm the workflow configuration and local
    commands pass.

  ## Out of scope

  • Django project setup and its home test are in task #1; Docker Compose/PostgreSQL configuration is in task #2.
  • Frontend asset checks for the Vite/React island are in task #18; do not add JavaScript linting or formatting here.

  ## Constraints

  • Keep changes to pyproject.toml, uv.lock after approval, AGENTS.md, the CI workflow file, and Python files that Ruff identifies in the existing scaffold.
  • Do not add Ruff as a runtime dependency, change product behavior, or reformat unrelated files.
  • Follow the root AGENTS.md dependency approval rule; do not add any dependency without asking first.


   ## 4. Add SkillSwap's custom email-based user model

  ## Goal

  Establish one email-based Django identity for each person, usable for both teaching and learning, before any project migrations are applied.

  ## Acceptance criteria

  ☐ Add a custom user model and manager with a unique normalized email login, Django password hashing, a nullable email-verification timestamp, and explicit
    active, suspended, deletion_pending, and deleted states.

  ☐ Set AUTH_USER_MODEL and create the account app's initial migration before applying any project migrations; confirm Django can migrate the configured
    database from a fresh database.

  ☐ Add tests for email normalization and duplicate rejection, password hashing, user creation, and authentication eligibility for each account state.

  ☐ Document the user fields and the requirement to create this model before other app migrations.

  ## Out of scope

  • Registration, login, logout, and password reset are in task #5; email verification delivery and gating are in task #6.
  • Google sign-in and provider identity linking are in task #7; the teaching/learning profile is in task #8.
  • Account deletion and retention behavior are in task #36; this task defines account states but not their workflows.

  ## Constraints

  • Keep changes to the accounts app model/manager/initial migration, project AUTH_USER_MODEL settings, focused user-model tests, and the brief migration-
    ordering documentation.

  • Use Django's built-in authentication and password-hashing support; do not add an authentication dependency.

  • Create this migration before running initial migrations for other project apps, and follow the root AGENTS.md rule requiring approval before adding
    dependencies.

 ## 5. Add email/password registration, login, logout, and reset

  ## Goal

  Let visitors register and manage a SkillSwap account with email and password using Django's built-in authentication protections.

  ## Acceptance criteria

  ☐ Provide server-rendered registration, login, logout, and password-reset pages using the custom user model from task #4; new registrations remain
    unverified until task #6's verification flow is completed.

  ☐ Authenticate by normalized email, permit login only for accounts in the active state, and use CSRF-protected forms and Django's password hashing.

  ☐ Configure password-reset email delivery through Django's email backend and settings; return the same confirmation response whether or not the submitted
    email belongs to an account.

  ☐ Add tests/test_auth.py for registration, duplicate normalized emails, successful/failed login, inactive account states, logout, password-reset link use
    and expiry, and non-enumerating reset responses; uv run pytest tests/test_auth.py and uv run pytest pass.

  ## Out of scope

  • Email-verification delivery and the trust-sensitive action gate are in task #6; unverified users may sign in but remain subject to that gate.
  • Google sign-in and account linking are in task #7; profile setup is in task #8.

  ## Constraints

  • Keep changes to authentication forms/views/URLs, their Django templates, email settings needed for password reset, and tests/test_auth.py.

  • Use Django's built-in authentication and password-reset functionality; do not add an authentication dependency.

  • Do not add Google OAuth, send verification emails, or allow non-active account states to authenticate; follow AGENTS.md and request approval before
    adding any dependency.

 ## 6. Verify email addresses before trust-sensitive actions

  ## Goal

  Let users prove control of their account email and enforce verification before they publish listings or share live-session meeting links.

  ## Acceptance criteria

  ☐ Send a time-limited verification link when a user registers, using the account and email-verification timestamp from task #4 and Django's configured
    email backend; use a configurable expiry with a 24-hour default.

  ☐ On valid confirmation, set email_verified_at once and show a success state; handle invalid, expired, and already-used links without revealing private
    account details or marking the account verified on email-delivery failure.

  ☐ Provide a reusable server-side verification permission check and test that unverified users are denied while verified users pass; task #9 must apply it
    before listing publication and task #21 before meeting-link disclosure.

  ☐ Add tests for email content/link, valid/invalid/expired/replayed tokens, gate behavior, and delivery failure; uv run pytest passes.

  ## Out of scope

  • Registration, login, logout, and password reset are in task #5; Google OAuth and identity linking are in task #7.
  • Building listing publication and booking/meeting-link features belongs to tasks #9 and #21, which must call this task's verification gate.
  • Email verification is not required for login or private messaging; those rules remain in their respective tasks.

  ## Constraints

  • Keep changes to verification email/template, account verification view/URL, reusable permission check, verification settings, and focused authentication
    tests.

  • Use Django signing/authentication and the configured Django email backend; do not add a verification dependency.

  • Do not allow a client-submitted flag to mark an account verified, and follow AGENTS.md by requesting approval before adding any dependency.



 ## 7. Add Google sign-in

  ## Goal

   Let a person create or access their single SkillSwap account through Google OpenID Connect, while preventing unverified or ambiguous provider identities
  from being linked to an account.

  ## Acceptance criteria

  ☐ Use a maintained Django OAuth/OpenID Connect integration for Google; request approval under AGENTS.md before adding its dependency and declare it in
    pyproject.toml only after approval.

  ☐ Configure the Google client ID, client secret, and callback URL through environment settings, with non-secret examples documented and no credentials
    committed.

  ☐ Store Google's stable subject identifier as a unique external identity linked to the custom user; repeat sign-ins for that subject resolve to the same
    account.

  ☐ Accept a new Google identity only when the provider response confirms the email is verified. Never silently link or merge accounts based only on
    matching email; linking Google to an existing account requires the user to be authenticated and explicitly complete the provider flow.

  ☐ Use the integration's protections for OAuth state and nonce validation, reject provider errors and identities already linked to another account, and
    allow authentication only for accounts eligible under task #4.

  ☐ Add mocked-provider tests for first and repeat sign-in, provider error, invalid state/nonce, unverified email, duplicate identity, inactive account, and
    explicit account linking; uv run pytest passes.

  ## Out of scope

  • Email/password registration, login, logout, and reset are in task #5; email verification delivery and its trust-sensitive action gate are in task #6.
  • Profile creation is in task #8; do not add other identity providers or account-merging workflows here.

  ## Constraints

  • Keep changes to Google authentication integration, external identity model/migration, environment-based settings and URL configuration, focused
    templates, tests, and setup documentation.

  • Reuse the custom user model from task #4 and keep provider tokens/secrets out of logs and tracked files.

  • Follow the root AGENTS.md dependency-approval rule; do not add a dependency until approval is given.

  

## 8. Build the shared profile and skill-interest pages

## Goal

Give each account one profile for both teaching and learning, with privacy controls and a reusable skill-interest catalog for later listings and discovery.

## Acceptance criteria

- [ ] Add a profile linked one-to-one to the custom user, with display name, bio, languages, and visibility set to `members_only` by default; allow `public`, `members_only`, and `private` visibility values.
- [ ] Define visibility consistently: public profiles can be viewed by anyone, members-only profiles by authenticated users, and private profiles only by their owner and authorized staff; enforce this on profile read requests, not only in templates.
- [ ] Exclude account email, password data, and account status from profile views and responses. Let owners view and edit only their own profile; reject attempts to edit another account's profile.
- [ ] Add optional project and certificate profile records; users can add, edit, and remove their own items, while empty profiles remain valid.
- [ ] Add normalized `Skill` records and a profile-skill relation that records whether the user teaches or wants to learn each skill and their self-reported level; prevent duplicate records for the same skill/intent on one profile and validate allowed levels.
- [ ] Render server-side profile view and edit pages using Django templates, Tailwind, HTMX, and Alpine.js where interaction needs them; add tests for profile creation/uniqueness, optional items, skill validation and duplicates, visibility for anonymous/member/owner/staff viewers, and cross-user edit denial. `uv run pytest` passes.

## Out of scope

- Account creation and authentication are in tasks #4–#7; this task uses the existing custom user and account flows.
- Skill categories, listing creation/publication, search, follows, ratings, and reviews are handled by later tasks; task #9 must reuse this skill catalog and relation rather than create a parallel skill catalog.
- Profile completion requirements, avatar uploads, and public portfolio/media hosting are not part of this task.

## Constraints

- Keep changes to the `profiles` app models/migrations, profile and skill forms/views/URLs/templates, focused tests, and profile setup documentation.
- Use the existing Django, template, HTMX, Alpine.js, and Tailwind setup; do not add dependencies without approval under `AGENTS.md`.
- Enforce owner and visibility checks in server-side view/service logic, and do not store private account fields redundantly on the profile.


## 9. Add categorized live-lesson and transcript listings

## Goal

Let teachers create and submit structured live-lesson and transcript listings for review, and show learners only listings that have been approved for publication.

## Acceptance criteria

- [ ] Add admin-managed categories and associate them with the normalized `Skill` records from task #8; listings reference the shared skill/category records rather than creating a second skill catalog.
- [ ] Add listings with an owner, type (`live` or `transcript`), skill/category, title, description, learning outcomes, skill level, and state (`draft`, `pending_review`, `published`, `rejected`, or `removed`); live lessons also require a duration, while transcript-specific fields are deferred to the transcript workflow.
- [ ] Let an owner create and edit their own drafts and submit them for review; prevent edits to another owner's listing and define valid state transitions so only authorized staff can publish or reject pending listings and removed listings are not learner-visible.
- [ ] Validate required fields and type-specific fields. Keep suggested point values configurable, with the plan's proposed 10 points for a live lesson and 2–5 points for a transcript recorded as defaults pending product confirmation.
- [ ] Add tests for type/field validation, point configuration and bounds, ownership, allowed state transitions, staff decisions, and visibility of drafts/rejected/removed versus published listings; `uv run pytest` passes.

## Out of scope

- Skill catalog/profile interests are in task #8; PostgreSQL search and filters are in task #10.
- Booking and point transfers/reservations are in tasks #13 and #21; recording intake, transcription, and transcript editing are in tasks #24–#27.
- Do not add a separate moderation queue; staff may use Django Admin for listing review.

## Constraints

- Keep changes to the catalog/listing app models and migrations, owner/staff forms and views, Django Admin configuration, templates, focused tests, and concise setup documentation.
- Use the existing Django templates, Tailwind, HTMX, and Alpine.js stack; do not add dependencies without approval under `AGENTS.md`.
- Apply listing visibility and state authorization in server-side queries and actions, not only in templates.

## 10. Add PostgreSQL listing search and filters

## Goal

Let learners find published listings through a server-rendered search page with composable filters and stable result ordering.

## Acceptance criteria

- [ ] Add a GET-based Django search view using PostgreSQL full-text search over listing title, description, and learning outcomes with the `simple` text-search configuration.
- [ ] Support combined filters for category/skill, listing type, skill level, teacher language, and minimum/maximum point cost; preserve the submitted query and filters in pagination links.
- [ ] Rank text matches by PostgreSQL search rank and use deterministic title/ID ordering for ties and for unqueried result sets.
- [ ] Return only published listings owned by active accounts whose profiles are visible to the requesting viewer; do not leak drafts, removed listings, or private-profile listings.
- [ ] Add PostgreSQL-backed tests for matching and non-matching terms, combined filters, pagination/query preservation, hidden and unpublished listings, and deterministic ordering; `uv run pytest tests/test_listing_search.py` and `uv run pytest` pass.

## Out of scope

- HTMX partial updates for the results are in task #16; rating filters depend on review aggregates and are in task #33.
- External search services, personalized recommendation ranking, and changes to listing creation are outside this task.

## Constraints

- Keep changes to the listing search query/service, Django view/URL/templates, focused PostgreSQL tests, and search documentation.
- Use PostgreSQL full-text search and existing Django facilities; do not add dependencies or external services without approval under `AGENTS.md`.
- Keep search read-only and enforce profile/listing access rules on the server for every request.

## 11. Add rule-based recommendations to the homepage

## Goal

Recommend relevant published lessons and transcripts using simple, explainable matches to a learner's profile and followed teachers.

## Acceptance criteria

- [ ] Implement a recommendation service that accepts a learner/profile and an explicit set of followed teacher IDs, and scores each eligible listing: exact wanted-skill match +5, stated-level match +2, shared profile language +1, and followed teacher +3.
- [ ] Return only published listings owned by active accounts and visible profiles; order by score and then stable listing title/ID, without using popularity signals.
- [ ] Diversify results so one teacher cannot fill the list, and reserve at most one slot in each ten-result block for an eligible teacher with fewer than three published listings when one is available.
- [ ] For learners without profile interests or language data, return a diverse eligible fallback list; render the results in the homepage recommendation section.
- [ ] Add tests for each scoring signal, ties/stable ordering, cold-start fallback, creator diversity, new-teacher exposure, and visibility filtering; `uv run pytest tests/test_recommendations.py` and `uv run pytest` pass.

## Out of scope

- Follow/unfollow UI and persistent follow relationships are in task #32; this service receives followed IDs as input so it can be tested independently.
- AI recommendations, popularity-based ranking, and search/filter behavior are outside this task.

## Constraints

- Keep changes to the recommendation service/query, homepage view/template integration, focused tests, and brief ranking documentation.
- Use Django/PostgreSQL data already defined in profile and listing tasks; do not add AI services or dependencies without approval under `AGENTS.md`.
- Keep ranking deterministic and enforce listing/profile visibility before returning results.

## 12. Add a PostgreSQL-backed job queue and worker

## Goal

Run durable background work through PostgreSQL and Django, with bounded retries and recovery after a worker stops unexpectedly.

## Acceptance criteria

- [ ] Add a `BackgroundJob` record containing an allowlisted job type, small JSON payload of record references, unique idempotency key, status, attempt count, run-after time, lease expiry, and sanitized error summary; do not store media bytes or secrets in payloads.
- [ ] Provide an enqueue service that creates a job in the same transaction as the database event that requires it, and deduplicates repeated requests by idempotency key.
- [ ] Add a `run_jobs` Django management command that claims due jobs using PostgreSQL row locks with `skip_locked`, commits a lease before invoking an idempotent handler, and records success or permanent failure.
- [ ] Retry transient errors with capped exponential backoff and a configurable maximum of five attempts by default; reclaim expired leases after worker crashes without running the same live lease concurrently.
- [ ] Document the Docker Compose worker command and test enqueue deduplication, competing workers, retry limits/backoff, expired-lease recovery, and handler idempotency against PostgreSQL; `uv run pytest` passes.

## Out of scope

- Specific transcription, notification, or reminder handlers are implemented in their owning tasks.
- Celery, Redis, and an external queue service are not part of this architecture.

## Constraints

- Keep changes to the operations/jobs app, migrations, enqueue/claim/worker code, management command, focused tests, Compose worker configuration, and operator documentation.
- Use Django and PostgreSQL primitives; do not add dependencies without approval under `AGENTS.md`.
- Limit job payloads and error output to non-sensitive identifiers and sanitized summaries.

## 13. Add the transactional points ledger

## Goal

Provide one auditable, concurrency-safe service for every SkillSwap point grant, transfer, spend, reservation, capture, and release.

## Acceptance criteria

- [ ] Add one `PointAccount` per user with cached integer available and reserved totals, append-only signed `PointTransaction` entries with bucket, type, actor, source reference, and unique idempotency key, and `PointReservation` records with `reserved`, `captured`, or `released` state.
- [ ] Provide atomic service functions for controlled issuance, user-to-user transfer/debit, reserve, capture-to-recipient, and release; disallow point purchases and non-positive amounts.
- [ ] Lock affected accounts in deterministic user-ID order, reject insufficient balances, write matching debit/credit entries for internal transfers, and keep cached totals consistent with the ledger.
- [ ] Make repeated calls with the same idempotency key return the prior outcome without a second mutation; never edit or delete posted ledger history, and use a reasoned compensating transaction for corrections.
- [ ] Add PostgreSQL tests for nonnegative balances, conservation, cache/ledger reconciliation, idempotency, append-only behavior, rollback after failure, and concurrent spending/reservations; `uv run pytest` passes.

## Out of scope

- Starter-point grant timing is in task #14; booking policy is in tasks #21–#23; transcript unlock behavior is in task #28.
- Product point values, real-money purchase, and staff UI for adjustments are handled elsewhere or require separate product decisions.

## Constraints

- Keep changes to the points app models/migrations, transactional service layer, focused PostgreSQL tests, and concise ledger usage documentation.
- Use Django database transactions and PostgreSQL locking; do not add dependencies without approval under `AGENTS.md`.
- Enforce append-only ledger behavior in application permissions and service APIs; only ledger services may change cached balances.

## 14. Issue one configurable starter grant to verified accounts

## Goal

Grant each eligible new account its starter points exactly once after its email or Google identity is verified.

## Acceptance criteria

- [ ] Add one account-verification service that ensures the user's `PointAccount` exists and calls task #13's grant service inside the same database transaction.
- [ ] Invoke the service after successful email verification and after verified Google sign-in; repeated verification callbacks and retries must not grant a second award.
- [ ] Require an active, verified account and reject grants for unverified, suspended, deletion-pending, or deleted accounts.
- [ ] Configure the grant using `STARTER_POINTS`, with the proposed default of 20 pending product confirmation; derive a unique source/idempotency key from the user ID.
- [ ] Add PostgreSQL-backed tests for eligibility, email/Google paths, duplicate events, retry/concurrent callbacks, and agreement between account totals and ledger entries; `uv run pytest` passes.

## Out of scope

- Ledger mechanics are implemented in task #13; verification messages and Google provider flow are implemented in tasks #6 and #7.
- Changing the proposed starter amount or defining the broader point economy is a product decision, not part of this implementation.

## Constraints

- Keep changes to the account verification service/integration points, point-grant configuration, focused tests, and brief configuration documentation.
- Reuse the existing point-ledger API and provider verification state; do not create a second balance or grant mechanism.
- Follow `AGENTS.md` and do not add dependencies without approval.

## 15. Add the responsive Django template foundation with Tailwind

## Goal

Establish shared, responsive Django page components and a reproducible Vite/Tailwind asset build for the web interface.

## Acceptance criteria

- [ ] Add a Vite asset pipeline integrated with Django static files and configure Tailwind to scan the project's templates and compile production assets with a manifest under `static/build/`.
- [ ] Add a shared Django base template with semantic navigation and content regions plus reusable responsive form, button, alert, and spacing styles.
- [ ] Ensure Django resolves development and production assets correctly and that core pages and forms remain usable without JavaScript.
- [ ] Document frontend dependency installation and development/production build commands; verify the app serves built assets and `npm run build` and `uv run pytest` pass.

## Out of scope

- React mounting and the retro-board island are in task #18; this task establishes the shared Vite pipeline they will extend.
- Search-specific HTMX behavior and Alpine interactions are handled in tasks #16 and #17.

## Constraints

- Keep changes to frontend package/lock/config files, Tailwind/Vite configuration, Django static asset integration, base/shared templates and styles, focused tests, and frontend documentation.
- Request approval before adding frontend dependencies under `AGENTS.md`; add approved packages only to the appropriate package manifest and lockfile.
- Do not introduce a separate frontend application or make essential navigation/forms depend on JavaScript.

## 16. Add HTMX updates to listing search and filters

## Goal

Let learners update search results and pagination without a full-page reload while keeping Django authoritative for filtering and access control.

## Acceptance criteria

- [ ] Extend task #10's GET search form and pagination links to request the same query through HTMX and replace only the results region.
- [ ] Preserve query and filter parameters in the address bar/history, show a loading indicator, and render an explicit empty-results state.
- [ ] Return the full search page for ordinary requests and a dedicated results partial for HTMX requests; both paths use the same search/query and visibility service and produce equivalent results.
- [ ] Keep search submission and pagination usable when JavaScript is disabled.
- [ ] Test equivalence of ordinary/HTMX results, retained URL state, pagination, empty results, and exclusion of hidden/unpublished listings; `uv run pytest tests/test_listing_search.py` and `uv run pytest` pass.

## Out of scope

- Search ranking and filter definitions are in task #10; do not change business rules or add client-side filtering.
- Other HTMX interactions are handled by the feature tasks that own them.

## Constraints

- Keep changes to listing-search templates/partials, HTMX attributes and response selection, focused search tests, and search documentation.
- Use the existing HTMX asset integration; do not add dependencies without approval under `AGENTS.md`.
- Keep server-side query, authorization, and visibility behavior identical for full-page and partial requests.

## 17. Add Alpine.js for a progressive-enhancement alert

## Goal

Make a shared Django alert dismissible with an accessible small client-side interaction and a useful no-JavaScript fallback.

## Acceptance criteria

- [ ] Bundle and initialize Alpine.js through the existing Vite pipeline and use it to dismiss the shared alert.
- [ ] Provide a semantic, keyboard-operable dismiss button that becomes available only when Alpine is initialized; without JavaScript, keep the alert content visible and hide the nonfunctional button.
- [ ] Ensure the built asset is served through Django and add a test for the alert's rendered fallback and control markup.
- [ ] Manually verify click and keyboard dismissal and the no-JavaScript fallback at mobile and desktop widths; document the check.

## Out of scope

- Other client-side interactions and React island behavior are in their owning tasks; do not make core navigation or forms depend on Alpine.

## Constraints

- Keep changes to the existing Vite entry/config, shared alert template/styles, focused markup test, and brief frontend documentation.
- Use the already approved Alpine.js integration; request approval before adding any dependency not already authorized by `AGENTS.md`.
- Preserve visible alert text and a functional page when JavaScript is unavailable.

## 18. Mount a Vite-built React island in one Django template

## Goal

Mount the retro board's React interface in exactly one server-rendered Django page while keeping the rest of SkillSwap server-rendered.

## Acceptance criteria

- [ ] Extend task #15's Vite build with a dedicated React/ReactDOM entry and configure Django's asset-manifest integration to resolve development and production assets from `static/build/`.
- [ ] Mount that entry point in exactly one Django template and provide an accessible static fallback if the React bundle cannot run.
- [ ] Load the React bundle only on the retro-board page; do not create a separate frontend application or backend service.
- [ ] Add a test that the template renders one mount point and references the expected built entry; document Vite development/build and Django `collectstatic` commands.
- [ ] Verify `npm run build` and `uv run pytest` pass.

## Out of scope

- Retro-board data/API behavior is in task #19; do not implement business logic in this mount task.
- React is not used to replace Django pages outside the single island.

## Constraints

- Keep changes to frontend package/config/lock files as approved, the React entry/mount component, one Django template, asset-manifest integration, focused tests, and build documentation.
- Request approval before adding React-related dependencies under `AGENTS.md`.
- Use the existing Vite and Django static-file workflow and preserve a server-rendered page shell.

## 19. Implement the minimal personal retro board

## Goal

Let an authenticated user manage a private retrospective board in the React island, backed by Django-owned data and authorization.

## Acceptance criteria

- [ ] Implement the stated MVP assumption because the plan does not specify this feature: each account has a private board with “Went well,” “Could improve,” and “Actions” columns containing text cards; there is no sharing, voting, comments, or real-time collaboration.
- [ ] Add a `RetroCard` model and owner-scoped Django JSON endpoints to create, read/list, edit, delete, and move the current user's cards among the three columns.
- [ ] Require authentication and enforce ownership on every endpoint; requests from one account must not read or change another account's cards, and state-changing endpoints must retain CSRF protection.
- [ ] Connect the React island from task #18 to these endpoints and provide useful loading, empty, validation, and error states.
- [ ] Add API and component tests for card interactions, column moves, unauthenticated access, cross-account isolation, and invalid input; verify `npm test`, `npm run build`, and `uv run pytest` pass.

## Out of scope

- Shared boards, collaboration, voting, comments, notifications, and analytics are not part of this MVP assumption.
- React mounting/asset delivery is in task #18; do not build a separate backend or frontend service.

## Constraints

- Keep changes to the retro-board app models/migrations, owner-scoped JSON views/URLs, the existing React island, focused API/component tests, and concise documentation.
- Use existing Django/React tooling; request approval under `AGENTS.md` before adding test or runtime dependencies.
- Keep authorization and data rules in Django, not solely in the React client.

## 20. Let teachers manage weekly availability and date exceptions

## Goal

Let teachers define recurring local-time windows and date-specific changes when learners may request live lessons.

## Acceptance criteria

- [ ] Add owner-scoped availability rules containing weekday, local start/end time, and an IANA timezone; add date-specific exceptions that replace the teacher's normal windows on that local date.
- [ ] Validate timezone names, require end time after start time, and reject overlapping windows for the same weekday or exception date.
- [ ] Provide server-rendered create, edit, and delete pages; show saved times in the teacher's configured timezone and reject edits by other users.
- [ ] Preserve recurring values as local wall-clock times; document that task #21 converts a selected date and duration into a concrete UTC slot.
- [ ] Test ownership, weekly recurrence, exception precedence, invalid/overlapping ranges, and daylight-saving offset changes; `uv run pytest` passes.

## Out of scope

- Booking-slot generation, UTC conversion for selected lesson dates, and booking creation are in task #21.
- Cancellation, completion, and no-show outcomes are in tasks #22–#23.

## Constraints

- Keep changes to scheduling availability models/migrations, owner-scoped forms/views/URLs/templates, focused tests, and brief timezone documentation.
- Use Python/Django timezone support and IANA zones; request approval before adding dependencies under `AGENTS.md`.
- Do not store recurring rules as fixed UTC times or let clients bypass owner/time validation.

## 21. Book a live lesson and reserve its points atomically

## Goal

Let a verified learner book an available live lesson without double-booking either participant or spending points twice.

## Acceptance criteria

- [ ] Add a server-rendered slot selection/confirmation flow and a `Booking` record with listing, learner, teacher, UTC start/end, display IANA timezone, scheduled status, and optional external meeting URL.
- [ ] Allow booking only for a published live listing, an eligible email-verified learner, a different teacher, and a slot that conforms to the teacher's task #20 availability and lesson duration.
- [ ] Convert the requested local date/time to UTC; reject nonexistent daylight-saving times and require an explicit offset to disambiguate repeated local times. Store UTC instants and the selected display timezone.
- [ ] On submission, lock participant rows in deterministic ID order, recheck availability and overlaps for both participants, then create the booking and reserve the listing's configured point cost through task #13's ledger in one database transaction.
- [ ] Use a request idempotency key so safe retries cannot create a second booking or reservation; expose any meeting URL only to the two participants and authorized staff.
- [ ] Test valid/invalid booking, self-booking, listing state/type, participant conflicts, insufficient points, idempotent retries, concurrent slot claims, DST cases, and meeting-link authorization against PostgreSQL; `uv run pytest` passes.

## Out of scope

- Completion and disputes are in task #22; cancellation and no-show policy is in task #23.
- Availability editing is in task #20; point-ledger mechanics are in task #13.

## Constraints

- Keep changes to scheduling booking models/migrations, slot/confirmation views/templates, transactional booking service, focused PostgreSQL tests, and user-facing booking documentation.
- Use the existing ledger service and PostgreSQL transactions/locking; do not add dependencies without approval under `AGENTS.md`.
- Enforce verified-user eligibility and meeting-link privacy server-side on every request.

## 22. Add booking completion and dispute handling

## Goal

Capture reserved points only after both booking participants confirm completion, and keep disputed reservations held for an auditable admin decision.

## Acceptance criteria

- [ ] Add participant-scoped completion confirmations and explicit transitions from scheduled booking to completed or disputed; reject actions by nonparticipants and accounts ineligible to act.
- [ ] Capture the learner's point reservation for the teacher atomically when both participants confirm; duplicate confirmations must not capture twice.
- [ ] If either participant disputes completion, retain the reservation and expose the case only to participants and authorized staff; let authorized staff capture or release it with a required decision and reason recorded in an audit record.
- [ ] Make the deadline for the second participant's response configurable; when it expires without agreement, flag/escalate the booking for review without automatically capturing or releasing points.
- [ ] Test permissions, repeat confirmations/resolutions, deadline escalation, held/captured/released ledger consistency, and audit details; `uv run pytest` passes.

## Out of scope

- Cancellation and no-show outcomes are in task #23; booking creation and point reservation are in task #21.
- Admin dispute screens and broader point adjustments are in task #35.

## Constraints

- Keep changes to booking completion/dispute fields and migrations, participant/staff actions, transactional service logic, focused tests, and brief operations documentation.
- Reuse task #13's reservation/ledger service; never directly mutate balances or ledger entries.
- Keep the response deadline configurable and do not invent a permanent product policy value without approval.

## 23. Add cancellation and no-show policy enforcement

## Goal

Apply approved cancellation and attendance rules consistently and show users the relevant point consequences before booking.

## Acceptance criteria

- [ ] Before implementation, record the approved free-cancellation deadline, late-cancellation outcome, no-show evidence standard, and disputed-case handling in `docs/outdated/plan.md`; do not choose unresolved policy values in code.
- [ ] Add explicit booking transitions for timely cancellation, late cancellation, learner no-show, and teacher no-show, with point reservation capture/release outcomes exactly matching the approved policy.
- [ ] Record who initiated each action, when it occurred, and the evidence/reason required by the approved no-show policy; if evidence or outcome is disputed, retain the reservation pending review.
- [ ] Show the applicable cancellation deadline and point consequences before the learner confirms a booking.
- [ ] Test deadline boundaries, participant permissions, repeated submissions, evidence/dispute behavior, and each approved outcome against PostgreSQL; `uv run pytest` passes.

## Out of scope

- Booking creation/reservation is in task #21; completion/dispute confirmation is in task #22.
- Do not define reputation penalties or unresolved cancellation/no-show policy in implementation code.

## Constraints

- Keep changes to approved policy documentation, booking transition/service logic, user-facing policy display, focused tests, and operational guidance.
- Reuse task #13's ledger/reservation services and preserve audit history; do not directly adjust point balances.
- Pause only the policy-dependent implementation if product approval is not available; complete independent documentation or preparation without guessing policy.

## 24. Add recording intake and temporary-file lifecycle

## Goal

Accept an authorized recording for transcription while ensuring uploaded and derived media are temporary processing inputs, never retained as product files.

## Acceptance criteria

- [ ] Add authenticated recording intake with configured allowed audio/video formats, maximum size, and maximum duration; enforce limits on the server and reject invalid or unsupported uploads.
- [ ] Ignore client filenames for storage paths, generate opaque temporary paths, and queue only a temporary input reference; do not persist media bytes or a durable file path in PostgreSQL or permanent object storage.
- [ ] Delete source and derived files after success, provider/worker failure, timeout, and stale-job cleanup; when media is removed, retry requires a fresh upload.
- [ ] Ensure files are inaccessible to other users and are not exposed through public URLs; test valid intake, invalid upload, authorization, all configured limits, and cleanup for every exit path.
- [ ] Test that successful and failed processing leaves no durable media copy and that stale temporary files are discovered and removed.

## Out of scope

- ffmpeg conversion is in task #25; Whisper calls and transcript persistence are in task #26.
- Transcript review/publication and retention policy are in tasks #27 and #36.

## Constraints

- Keep changes to transcription intake, temporary storage lifecycle, job enqueue reference handling, focused tests, and configuration/documentation for media limits.
- Use temporary processing storage only; do not introduce persistent file storage or expose media paths to clients.
- Follow `AGENTS.md` and do not add dependencies without approval.

## 25. Add ffmpeg audio extraction

## Goal

Convert accepted audio or extract audio from accepted video into an input format supported by the transcription workflow.

## Acceptance criteria

- [ ] Install ffmpeg in the Docker Compose image used by the processing worker and invoke it from the processing service for supported audio/video inputs.
- [ ] Produce the configured Whisper-compatible audio format using generated temporary paths; reject malformed media and video without an audio stream.
- [ ] Invoke ffmpeg using an argument array (never a shell-built command) and enforce configured duration, CPU, disk, and execution-time limits.
- [ ] Delete both source and derived temporary files on success, conversion error, invalid input, and timeout.
- [ ] Test representative audio/video formats, malformed/audio-less inputs, resource-limit failures, safe argument handling, and cleanup for each outcome.

## Out of scope

- Upload authorization, intake limits, and temporary lifecycle ownership are in task #24; transcription provider calls are in task #26.
- Persistent media storage or user-accessible download links are not part of the architecture.

## Constraints

- Keep changes to the worker Dockerfile/Compose configuration, ffmpeg extraction service, focused tests, and processing documentation.
- Use the system ffmpeg executable and existing temporary-file workflow; do not add a Python ffmpeg wrapper dependency without approval under `AGENTS.md`.
- Never interpolate client input into shell commands or retain source/derived media after processing.

## 26. Add OpenAI Whisper transcription jobs

## Goal

Create a private transcript from an accepted recording through OpenAI Whisper and expose the processing status to its owner.

## Acceptance criteria

- [ ] Connect the task #12 PostgreSQL worker to OpenAI Whisper and enqueue transcription for accepted inputs from tasks #24–#25; expose status only to the recording owner and authorized staff.
- [ ] Persist transcript text and only the minimum provider metadata needed by the product, subject to approved consent and retention policy; media itself remains temporary and is deleted after processing outcomes.
- [ ] Make job completion idempotent, classify transient/permanent provider failures, and bound retries to the input's short-lived processing window; after media deletion, require a fresh upload to retry.
- [ ] Read API credentials and model/configuration from environment settings; never log credentials, recording contents, or transcript text.
- [ ] Mock provider calls in tests for success, timeout, rate limit, invalid response, retry exhaustion, duplicate delivery, unauthorized status access, and cleanup; `uv run pytest` passes.

## Out of scope

- User transcript editing/review/publication is in task #27; LLM-generated suggestions are in task #29.
- Durable recording storage, automatic publication, and learner transcript access/charging are outside this task.

## Constraints

- Keep changes to transcription provider/worker integration, transcript/job model fields and migrations, owner/staff status view, focused tests, and secret/configuration documentation.
- Use OpenAI Whisper and the existing PostgreSQL job worker; request approval before adding an SDK dependency under `AGENTS.md`.
- Respect the approved consent/retention policy and redact sensitive content from logs and errors.

## 27. Add user review and publication for transcripts

## Goal

Let a recording owner review and correct a generated transcript, complete its listing details, and submit it for moderation before learners can discover it.

## Acceptance criteria

- [ ] Provide a private owner-only review page for transcript text, with editing and required listing details before submission; prevent other users from reading or changing a draft.
- [ ] Enforce explicit `draft`, `pending_review`, `published`, and `removed` states with owner and authorized moderator transitions; record moderation decisions and prevent owners from self-publishing pending content.
- [ ] Show only published transcripts with valid listing details in discovery; editing published content returns it to the configured review state and removes it from learner discovery until approved again.
- [ ] Apply the approved transcript retention/deletion behavior on edits, rejection, removal, and account actions; do not create media download links or expose the temporary recording.
- [ ] Test draft privacy, ownership, staff moderation, publication visibility, edit/state transitions, and transcript retention behavior; `uv run pytest` passes.

## Out of scope

- Recording intake and provider transcription are in tasks #24–#26; paid learner access is in task #28.
- OpenAI-generated writing suggestions are in task #29.

## Constraints

- Keep changes to transcript review forms/views/templates, listing/transcript state transitions, moderator actions, focused tests, and user-facing review instructions.
- Use existing Django templates, Tailwind, HTMX, and Alpine.js; do not add dependencies without approval under `AGENTS.md`.
- Enforce owner/moderator authorization server-side and apply the approved consent and retention policy.

## 28. Add point-based transcript access

## Goal

Let learners unlock a published transcript once, revisit it in their library, and let its creator read it without paying.

## Acceptance criteria

- [ ] Let an eligible learner request access only to a currently published transcript/listing; atomically check available points, write immutable learner-debit and creator-credit entries through task #13's ledger service, and create a unique entitlement.
- [ ] Make repeated or concurrent unlock requests idempotent: return the existing entitlement without charging twice, including when a prior request completed but its response was lost.
- [ ] Let a transcript creator read their own transcript without payment and list each learner's unlocked transcripts in that learner's library.
- [ ] On every transcript read, verify creator status or entitlement plus current listing publication, account, and visibility rules; an unpublished, removed, or otherwise inaccessible transcript must not be served through a stale entitlement.
- [ ] Test concurrent/repeated unlocks, insufficient balance, ledger consistency, creator access, library visibility, and access after unpublishing/removal against PostgreSQL; `uv run pytest` passes.

## Out of scope

- Transcript creation/review/publication is in tasks #26–#27; booking and live lesson reservations are in task #21.
- This task does not change listing moderation or retention decisions.

## Constraints

- Keep changes to transcript entitlements/library query and views, transactional unlock service, focused PostgreSQL tests, and learner-facing access documentation.
- Use task #13's append-only ledger and PostgreSQL transactions; do not update cached balances directly.
- Enforce current authorization at content read time, not only when the entitlement is created.

## 29. Add OpenAI LLM text assistance

## Goal

Offer transcript owners editable learning-outcome suggestions while keeping all content and publication decisions under the owner's control.

## Acceptance criteria

- [ ] Let a transcript owner explicitly request suggested learning outcomes for their transcript; verify ownership before enqueueing a task #12 background job.
- [ ] Send only the transcript text needed for this request to OpenAI and use configured model, API key, timeout, and bounded retry settings.
- [ ] Store the result as an attributable editable draft; never replace existing listing text or publish content unless the owner explicitly accepts the suggestions.
- [ ] Keep authorization, validation, moderation, and publication rules in Django application code; an LLM response cannot make business or access decisions.
- [ ] Avoid logging transcript text, prompts, or credentials; test mocked success, provider failure, timeout, retry exhaustion, duplicate delivery, unauthorized requests, and draft acceptance without automatic publication; `uv run pytest` passes.

## Out of scope

- Transcription is provided by Whisper in task #26; this feature does not transcribe new media or publish listings.
- General-purpose chat, recommendations, and other LLM features are not part of this task.

## Constraints

- Keep changes to the transcript assistance request/worker/result handling, focused tests, and concise configuration/privacy documentation.
- Use the existing OpenAI integration/configuration and PostgreSQL worker; request approval before adding an SDK dependency under `AGENTS.md`.
- Minimize transmitted data and redact prompts, transcript content, and credentials from logs/errors.

## 30. Add private messaging

## Goal

Let users communicate through private text conversations with server-rendered pages and HTMX updates.

## Acceptance criteria

- [ ] Add one-to-one conversations and persisted text-only messages, with server-rendered inbox and conversation pages and HTMX send/refresh behavior.
- [ ] Enforce participant authorization on every inbox, conversation, message-read, send, and HTMX-refresh request; users cannot discover or access conversations they do not participate in.
- [ ] Honor task #34 blocks by preventing new messages between users who block one another; existing conversation history remains visible only to its participants.
- [ ] Validate message length and sending rate on the server, escape user text in rendered responses, and protect state-changing forms with CSRF.
- [ ] Test conversation isolation, cross-user access, block behavior, invalid/oversized and rate-limited messages, CSRF-protected sends, safe rendering, and HTMX partial responses; `uv run pytest` passes.

## Out of scope

- Email or in-app notifications are in task #31; block/report/moderation workflows are in task #34.
- Attachments, voice/video calls, public comments, and real-time websocket delivery are not included.

## Constraints

- Keep changes to communications models/migrations, inbox/conversation views and templates, HTMX partials, focused tests, and brief messaging guidance.
- Use Django templates, HTMX, and existing database infrastructure; do not add dependencies without approval under `AGENTS.md`.
- Never expose message text in notification payloads, logs, or unauthorized views.

## 31. Add in-app and email notifications

## Goal

Notify users about relevant messages, bookings, point changes, and reviews while keeping each notification private and delivery retryable.

## Acceptance criteria

- [ ] Add recipient-scoped in-app notifications for message, booking, point-transaction, and review events, with an inbox and mark-as-read action.
- [ ] Create each in-app notification idempotently in the same database transaction as its triggering event so retries do not duplicate it.
- [ ] Enqueue email delivery through task #12's PostgreSQL worker in the same transaction; retries are bounded and idempotent and provider failure does not erase the in-app notification.
- [ ] Add per-category preferences to mute non-essential in-app/email notifications, while documenting and preserving any essential account/security messages.
- [ ] Keep notification payloads free of private message text, meeting links, and other sensitive content; test recipient authorization, duplicate events, transactional enqueue, read state, preferences, and delivery retry handling; `uv run pytest` passes.

## Out of scope

- Message delivery/conversation behavior is in task #30; booking and point event generation remain in their feature tasks.
- Push notifications, SMS, and notification settings beyond the stated per-category controls are not included.

## Constraints

- Keep changes to notifications/preferences models and migrations, recipient-only views/templates, event hooks, worker email handler, focused tests, and configuration guidance.
- Use the existing PostgreSQL worker and configured Django email backend; do not add dependencies without approval under `AGENTS.md`.
- Do not include private content or secrets in stored notification payloads, email job payloads, or logs.

## 32. Add follows and a focused community feed

## Goal

Let members follow teachers and browse recent relevant listings alongside discovery listings from teachers they do not follow.

## Acceptance criteria

- [ ] Add authenticated follow/unfollow actions for teacher profiles; reject self-follows and enforce a unique follower/followed pair.
- [ ] Apply profile visibility, active-account, and block rules to follow actions and feed results; do not expose private or inaccessible profile activity.
- [ ] Render a paginated feed of recent published listings from followed teachers and a separate discovery section of recent public listings from teachers the viewer does not follow.
- [ ] When the viewer follows no one, show an empty-following state with eligible discovery listings; exclude drafts, rejected, removed, and private/inaccessible content from every section.
- [ ] Test follow permissions/uniqueness, visibility and block filtering, feed ordering/pagination, followed-versus-discovery separation, and the empty-following state; `uv run pytest` passes.

## Out of scope

- Recommendation scoring/homepage ranking is in task #11; review/rating-based ranking is in task #33.
- Forums, comments, and public user posts are not part of this feed.

## Constraints

- Keep changes to follow model/migration, owner/member actions, feed query/view/templates, focused tests, and concise feed documentation.
- Use Django templates and existing profile/listing/block data; do not add dependencies without approval under `AGENTS.md`.
- Enforce visibility and block filtering on the server for full and paginated requests.

## 33. Add lesson reviews and ratings

## Goal

Let actual participants review completed live lessons and calculate trustworthy profile and listing ratings from eligible visible reviews.

## Acceptance criteria

- [ ] After a booking reaches the completed state in task #22, allow each of its two participants to submit one review of the other participant and the associated live lesson.
- [ ] Require an integer rating from 1 to 5 and allow optional text subject to documented length/content validation; enforce one review per booking and author in the database and application.
- [ ] Reject reviews for pending, disputed, cancelled, unrelated, or otherwise incomplete bookings and prevent users outside the booking from submitting or reading private review data.
- [ ] Calculate public profile and live-listing aggregates only from eligible, visible reviews; authorized moderators can hide or restore a review with actor, time, and reason recorded in an audit record.
- [ ] Test eligibility, permissions, rating/text validation, duplicate prevention, aggregates, moderator hide/restore, and aggregate changes without deleting review history; `uv run pytest` passes.

## Out of scope

- Review submissions for transcripts or non-booking interactions are not part of this task.
- Search rating filters are added separately only after these aggregates exist; task #10 remains unchanged.

## Constraints

- Keep changes to reviews/ratings models and migrations, participant forms/views, moderation action, aggregate query/service, focused tests, and review guidance.
- Use completed bookings and existing trust/moderation rules; do not add dependencies without approval under `AGENTS.md`.
- Preserve review history and enforce eligibility/visibility server-side.

## 34. Add user and content reporting, blocking, and moderation

## Goal

Give users private reporting and blocking controls and give authorized staff auditable tools to respond to abuse or misleading content.

## Acceptance criteria

- [ ] Let authenticated users report another user or a listing/transcript with a required reason and optional validated details; allow reports to be viewed only by the reporter and authorized staff.
- [ ] Let users block and unblock other users; reject self-blocking, enforce unique block pairs, and apply blocks to new message sends and the blocker's feed/discovery results.
- [ ] Add a staff-only Django Admin report queue with resolution actions for no action, content removal/hiding, or account suspension; record moderator, decision, reason, target, and time in the audit history.
- [ ] Ensure removed/hidden content disappears from discovery and access checks, and suspended users cannot perform authenticated product actions.
- [ ] Test report privacy, block/unblock effects, staff-only moderation, required audit details, content access after removal, and suspended-account action rejection; `uv run pytest` passes.

## Out of scope

- Dedicated trust-and-safety staffing processes and appeals policy require product/operations decisions beyond the basic queue.
- Booking disputes and point-specific admin decisions are in task #35; report and block actions do not mutate the point ledger.

## Constraints

- Keep changes to trust/report/block models and migrations, account-action guard integration, Django Admin moderation, focused tests, and concise operator guidance.
- Use existing Django Admin and account states; do not add dependencies without approval under `AGENTS.md`.
- Do not reveal reports to reported users or expose removed content through cached/search/feed paths.

## 35. Add admin point and dispute controls

## Goal

Give authorized staff auditable read access to point history and safe controls to resolve held booking points or correct ledger errors.

## Acceptance criteria

- [ ] Provide staff-only Django Admin views to inspect point accounts and immutable ledger entries and review the booking context for disputed reservations.
- [ ] Allow authorized staff to resolve a held booking reservation by capturing it to the teacher or releasing it to the learner; require a decision and reason and record the staff actor, time, and linked ledger entries.
- [ ] Provide a separate audited adjustment action that creates compensating ledger transactions; never edit cached balances or posted transactions directly.
- [ ] Make dispute resolutions and adjustments idempotent so a repeated submission cannot apply a transaction twice; reject insufficient permission and missing reasons.
- [ ] Test non-staff and unauthorized staff access, capture/release atomicity, ledger/balance consistency, required audit fields, adjustment compensation, and repeat submissions; `uv run pytest` passes.

## Out of scope

- Booking dispute participant workflow is in task #22; general reporting/moderation is in task #34.
- This task does not allow deletion or editing of immutable point history.

## Constraints

- Keep changes to points/scheduling admin integration, audited decision/adjustment service, focused tests, and staff operating instructions.
- Reuse task #13's ledger and reservation services; enforce staff permissions server-side.
- Require a reason for every staff mutation and retain a link from decisions to resulting ledger entries.

## 36. Add transcript and account retention controls

## Goal

Apply approved consent, transcript/message retention, and account-deletion rules consistently while preserving only records the approved policy requires.

## Acceptance criteria

- [ ] Before implementing retention behavior, record approved transcript and message retention periods, recording/transcription consent requirements, and published-content behavior after account deletion in `docs/outdated/plan.md`; do not invent unresolved policy values in code.
- [ ] Provide an authenticated account-deletion request that revokes active sessions and product access immediately and runs the approved deletion/anonymization workflow.
- [ ] Delete or anonymize profile, external identity, message, transcript, and library data according to the approved policy; cancel pending transcription jobs and delete related temporary media.
- [ ] Retain only transaction/dispute records required by the approved policy, restrict any retained personal data to authorized staff, minimize deletion audit details, and never modify immutable point-ledger entries.
- [ ] Test each approved retention/deletion case, immediate access/session revocation, temporary media cleanup, staff permissions, and ledger integrity; `uv run pytest` passes.

## Out of scope

- Account state/model definition is in task #4; product consent and retention decisions must be recorded before dependent implementation.
- This task does not create new persistent media storage or change point transaction history.

## Constraints

- Keep changes to approved privacy-policy documentation, deletion request/workflow, affected app services, job/media cleanup hooks, focused tests, and user-facing deletion guidance.
- Apply documented decisions as explicit rules/configuration; do not guess policy or keep unnecessary personal data.
- Reuse the existing PostgreSQL worker and temporary-media lifecycle; follow `AGENTS.md` dependency rules.

## 37. Add operational monitoring and reconciliation commands

## Goal

Help operators identify unhealthy services, stuck jobs, temporary-media cleanup failures, provider errors, and point-account inconsistencies without exposing private data.

## Acceptance criteria

- [ ] Add Docker Compose readiness/health checks for Django, PostgreSQL, and the background worker, with dependency startup behavior that reflects actual readiness.
- [ ] Add a staff-only diagnostic command or view that reports failed/expired jobs, overdue queued work, stale temporary media, and provider/transcription errors using opaque record identifiers and sanitized summaries only.
- [ ] Add a read-only point reconciliation command that compares cached available/reserved totals with ledger-derived totals and reports affected opaque account IDs; it must never mutate accounts or ledger history.
- [ ] Require any balance correction to go through the audited adjustment action from task #35; document the operational sequence for investigating and correcting a mismatch.
- [ ] Emit structured logs with credentials, recordings, transcripts, and private message text redacted; test health failures, every diagnostic category, authorization, safe output, and that reconciliation leaves database values unchanged.

## Out of scope

- Automatic balance repair and general analytics dashboards are not included.
- Job processing, media lifecycle, point ledger, and admin adjustment behavior belong to tasks #12–#13, #24–#26, and #35.

## Constraints

- Keep changes to Compose health checks, staff-only diagnostics, read-only reconciliation command, focused tests, logging redaction, and operations documentation.
- Use existing Docker Compose, Django, PostgreSQL, and job records; do not add monitoring vendors or dependencies without approval under `AGENTS.md`.
- Never print secrets or user-content payloads in health, reconciliation, or diagnostic output.

## 38. Document local setup and MVP operating procedures

## Goal

Give a new contributor and an authorized operator enough verified instructions to set up, run, test, and safely operate the SkillSwap MVP.

## Acceptance criteria

- [ ] Write a fresh-checkout runbook with verified Docker Compose build/start/stop, migration, initial-admin, health-check, test, lint, frontend-build, and static-asset commands.
- [ ] Document required environment variables and Google OAuth/OpenAI configuration using placeholders only; never include credentials or real secrets.
- [ ] Document PostgreSQL backup and restore, diagnosing failed/expired jobs, handling transcription retries that require a fresh upload after temporary media cleanup, and point reconciliation plus audited correction procedures.
- [ ] List unresolved product/privacy decisions that must be settled before launch: point economy, booking/cancellation/no-show rules, moderation ownership, transcript consent/retention/content ownership, and how no-file-storage behavior replaces retained downloadable materials.
- [ ] Verify every documented command against the Docker Compose project and correct the runbook to match actual service names, settings, and command output.

## Out of scope

- Implementing missing application or infrastructure features is handled by their respective tasks; this task documents verified behavior and explicitly identifies gaps.
- Do not document unimplemented hosting platforms or file-storage services.

## Constraints

- Keep changes to the contributor/operator documentation in `README.md` and/or a focused operations document, plus links from existing project docs.
- Use only environment placeholders for secrets and refer to approved product policy; do not invent operational guarantees.
- Run documented commands against the repository's Docker Compose workflow and keep instructions consistent with `AGENTS.md`.
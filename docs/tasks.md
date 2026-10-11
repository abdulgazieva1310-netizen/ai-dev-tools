# SkillSwap MVP Backlog

## 1. Set up the empty Django project and a passing test
Goal: Create a minimal runnable Django project with one passing automated test.
Description: Initialize the repository as a Django project using the selected Python toolchain, add a minimal health or home endpoint, and configure pytest with pytest-django. Add a test that exercises that endpoint, document the local command to run it, and keep the project free of SkillSwap product features.

## 2. Add Docker Compose development services
Goal: Make the empty project and PostgreSQL database runnable together with Docker Compose.
Description: Add a Compose configuration for the Django web service and PostgreSQL, including environment-based settings, a persistent database volume, and a health check. Document the commands to build, start, migrate, and stop the local environment without adding production-specific hosting services.

## 3. Configure Ruff and automated quality commands
Goal: Give contributors a consistent Python lint and formatting workflow.
Description: Configure Ruff with the project's chosen Python version and reasonable lint/format rules, and document commands for checking and formatting the code. Ensure the empty project and its tests pass those checks.

## 4. Create the custom user and account settings
Goal: Establish SkillSwap's email-based user identity before adding other domain models.
Description: Implement a Django custom user model that uses email as the login identifier and includes account verification and active/suspended/deletion states. Add migrations and focused model tests, and document that the custom user model must be in place before other migrations are created.

## 5. Add email/password registration and login
Goal: Let a visitor create an account and sign in using email and password.
Description: Build Django views and templates for registration, login, logout, and password reset using Django's secure password handling and CSRF protections. Test successful flows, invalid credentials, duplicate email handling, and unauthenticated access behavior.

## 6. Add email verification
Goal: Require users to verify their email before using trust-sensitive features.
Description: Implement a time-limited verification flow that sends a confirmation link and records verification on successful use. Add tests for valid, expired, reused, and invalid links, and make the verification requirement available to other feature views as a reusable server-side check.

## 7. Add Google sign-in
Goal: Allow users to register and sign in with Google while retaining one SkillSwap account per person.
Description: Integrate Google OAuth through a maintained Django authentication package and link provider identities to the custom user model. Handle verified email and account-linking cases safely, and test the callback and failure paths with mocked provider responses.

## 8. Build profile and skill-interest management
Goal: Let each user maintain one profile for both teaching and learning.
Description: Add profile fields for display name, bio, languages, visibility, optional projects/certificates, and normalized skills the user teaches or wants to learn. Provide server-rendered create/edit pages and tests for validation, privacy settings, and ownership permissions.

## 9. Add skill categories and lesson listings
Goal: Let teachers publish structured live-lesson and recording/transcription listings.
Description: Add category, skill, and listing models with title, description, outcomes, level, format, duration where applicable, point price/reward, and publication/moderation state. Build owner-controlled listing create/edit/publish pages and tests for required fields and listing visibility.

## 10. Add listing search and filters
Goal: Help learners find relevant published listings using PostgreSQL search and structured filters.
Description: Implement search across listing titles and descriptions plus filters for category, level, format, language, rating, and point price where data exists. Add pagination and tests that ensure unpublished or moderated listings do not leak into results.

## 11. Add rule-based recommendations
Goal: Show useful listing recommendations without introducing an AI ranking dependency.
Description: Implement a small server-side ranking service using a learner's stated interests, skill level, language, followed teachers, and listing attributes. Include a way for newer teachers to appear and test the ranking with representative profiles and listings.

## 12. Add PostgreSQL-backed background jobs
Goal: Run retryable asynchronous tasks without Celery or Redis.
Description: Add a BackgroundJob model and a Django management command that claims due jobs safely with PostgreSQL row locking, leases work, retries transient failures with bounded backoff, and recovers expired leases. Test duplicate enqueueing, concurrent claim behavior, retry limits, and worker-crash recovery against PostgreSQL.

## 13. Add point accounts and immutable transaction ledger
Goal: Make every point balance change traceable and safe to retry.
Description: Add point-account, transaction, and reservation models with database constraints and idempotency keys, plus transactional service functions for grants, debits, transfers, holds, captures, and releases. Test that balances cannot go negative, transactions are not mutated, retries do not duplicate movements, and ledger totals reconcile with cached account totals.

## 14. Grant starter points to verified users
Goal: Give each verified new user the agreed initial point balance exactly once.
Description: Add a verified-account workflow that creates the point account and starter-grant ledger entry atomically. Keep the starter amount in configuration until the product owner confirms the value, and test repeated verification callbacks and account setup retries.

## 15. Add the responsive template foundation with Tailwind
Goal: Establish the shared page layout and responsive visual foundation.
Description: Configure Tailwind CSS for Django templates and add base navigation, page layout, form, button, and alert styles that work on mobile and desktop. Document the asset build command and ensure pages remain usable when interactive JavaScript is unavailable.

## 16. Add HTMX interactions to listing discovery
Goal: Update search results and filters without a full page reload while preserving server ownership of the UI.
Description: Add HTMX endpoints and Django partial templates for listing search/filter updates, loading and empty states, and pagination. Keep authorization and filtering in Django, and test both full-page and partial responses.

## 17. Add Alpine.js for small interface interactions
Goal: Support simple client-side menus and dialogs without expanding the frontend application.
Description: Include Alpine.js in the Django template asset pipeline and use it for one shared interaction such as a mobile navigation menu or confirmation dialog. Verify keyboard access, focus behavior, and graceful operation when JavaScript is unavailable.

## 18. Add the Vite-built React retro-board island
Goal: Mount the retro board as one isolated React feature inside a Django-rendered page.
Description: Configure Vite to build the React island and expose its generated asset manifest to Django templates. Mount it in exactly one Django template, keep data access behind Django endpoints, and document local and production asset build steps.

## 19. Add the React retro-board interface
Goal: Deliver the retro-board experience inside the established React island.
Description: Implement the board's agreed UI and interactions as a self-contained React component that mounts and unmounts cleanly within the Django page. Fetch and update board data through authenticated Django endpoints, and cover key rendering and interaction behavior with frontend tests.

## 20. Add teacher availability management
Goal: Let teachers define available time slots for live lessons.
Description: Add recurring availability rules and date-specific exceptions with explicit timezone handling, plus server-rendered management pages. Test daylight-saving boundaries, invalid ranges, and overlapping availability rules.

## 21. Add live-session booking and point reservation
Goal: Let learners book open lesson times while reserving the required points atomically.
Description: Implement booking creation that rechecks slot availability, locks the relevant booking/point records, and reserves points in the same database transaction. Prevent double booking and duplicate charges, and test simultaneous booking attempts against PostgreSQL.

## 22. Add booking completion and dispute handling
Goal: Transfer reserved points only after the agreed completion flow and preserve holds during disputes.
Description: Add participant completion confirmations, booking state transitions, and an admin dispute workflow that captures or releases the reservation with an audit record. Keep deadlines configurable until product policy is finalized, and test duplicate confirmations and admin resolutions.

## 23. Add cancellation and no-show policy enforcement
Goal: Apply visible, consistent point and booking outcomes for cancellation and no-shows.
Description: Implement the product-approved free-cancellation deadline, late-cancellation consequences, no-show evidence rules, and response deadline as explicit booking transitions. Add tests for each boundary and make the applicable rule visible before a learner confirms a booking; wait for the policy decision in `docs/plan.md` before fixing these outcomes.

## 24. Add recording intake and temporary-file lifecycle
Goal: Accept supported recordings for processing without retaining uploaded media.
Description: Add authenticated recording intake with configured type, size, and duration limits, generated temporary paths, and strict request timeouts. Ensure source and derived media are deleted after success, failure, timeout, and stale-job cleanup, with tests that verify no durable media copy remains.

## 25. Add ffmpeg audio extraction
Goal: Convert supported video or audio recordings into a Whisper-compatible audio input.
Description: Include ffmpeg in the web/worker container image and invoke it using argument arrays, generated paths, and CPU/time/resource limits. Test supported formats, malformed inputs, extraction failures, and cleanup of both original and derived temporary files.

## 26. Add OpenAI Whisper transcription jobs
Goal: Turn accepted recordings into persisted transcripts using OpenAI Whisper.
Description: Connect the PostgreSQL-backed worker to the OpenAI transcription API, record job status and minimal provider metadata, and persist transcript text only under the configured retention policy. Mock provider calls in tests and cover timeouts, rate limits, retries, invalid responses, idempotency, and recording deletion.

## 27. Add user review and publication for transcripts
Goal: Let recording owners inspect and publish transcription results as learning content.
Description: Build a transcript review/edit page with draft, published, and removed states, plus appropriate creator and moderator permissions. Test private drafts, publication visibility, edits, and deletion/retention behavior.

## 28. Add point-based transcript access
Goal: Let learners unlock a published transcript once and revisit it from their library.
Description: Implement the unlock transaction using the point ledger, enforce one charge per learner/transcript, and display unlocked transcripts in the learner's library. Test concurrent unlock attempts, insufficient balances, repeat access, creator access, and access revocation rules.

## 29. Add OpenAI LLM text assistance
Goal: Offer a narrow, reviewable LLM feature that helps creators improve transcript-derived learning content.
Description: Add a background job that sends only the user-requested text to OpenAI for a defined feature such as summary or suggested learning outcomes, with keys and model settings supplied through environment configuration. Keep generated output as an editable draft, avoid logging prompts or transcripts, and test mocked success, failure, retry, and timeout behavior.

## 30. Add private messaging
Goal: Let users communicate in text within the platform.
Description: Add conversations and messages restricted to their participants, with server-rendered conversation views and an HTMX refresh/send interaction. Test participant authorization, blocked-user rules, message validation, and safe rendering of user text.

## 31. Add in-app and email notifications
Goal: Notify users about messages, bookings, point changes, and reviews.
Description: Persist in-app notifications and enqueue durable email-delivery jobs in the same transaction as the event that triggers them. Add user preferences for non-essential email and test retries, idempotent delivery, read state, and preference enforcement.

## 32. Add follows and a focused community feed
Goal: Let users follow teachers and see relevant new listings.
Description: Add follow/unfollow actions and a feed of recent published listings from followed teachers plus selected community activity. Test privacy, pagination, and empty-feed recommendations without introducing public forums or comments.

## 33. Add lesson reviews and ratings
Goal: Let participants review genuine completed live lessons.
Description: Allow each participant to submit one review for a completed booking and calculate listing/profile ratings from eligible reviews. Test that pending, disputed, canceled, or unrelated bookings cannot generate reviews and that moderation can hide a review.

## 34. Add user and content reporting, blocking, and moderation
Goal: Give users and admins basic tools to respond to abuse and misleading content.
Description: Add report and block actions for users and listings/transcripts, plus an admin queue to review, resolve, and audit cases. Test access restrictions after blocking, report visibility, moderation actions, and account suspension effects.

## 35. Add admin point and dispute controls
Goal: Let authorized admins investigate and resolve point or booking cases with an audit trail.
Description: Configure Django Admin or focused admin views for point-ledger inspection, booking disputes, audited adjustments, and account/content actions. Restrict access to staff permissions and test that every resolution records an actor, reason, and immutable transaction history.

## 36. Add transcript and account retention controls
Goal: Apply user-visible privacy, transcript retention, and deletion rules consistently.
Description: Implement the product-approved transcript retention period, account deletion/anonymization workflow, and retained transaction/audit records. Add tests for deletion requests, staff access, transcript removal, and preservation of records required to explain point movements.

## 37. Add operational monitoring and reconciliation commands
Goal: Make failures in jobs, media processing, bookings, and point balances diagnosable.
Description: Add health checks and management commands or admin views for failed/stuck jobs, stale temporary files, and cached point totals that differ from the ledger. Emit structured error logs without secrets, recordings, or transcript contents, and document the local Compose commands for inspecting service health.

## 38. Document local setup and MVP operating procedures
Goal: Give a new contributor or administrator enough instructions to run and operate the MVP.
Description: Document Docker Compose setup, migrations, test/lint commands, required environment variables, OpenAI credentials, Google OAuth configuration, backup expectations, and common job recovery steps. Include the privacy and moderation decisions that must be finalized before a public launch.

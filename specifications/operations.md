# Operations & Runtime Requirements

The other spec files describe what the app *does*. This one describes how it behaves as a
*running system* — which is where most of "high-performance and scalable" actually lives.

Most of this file is gated. A local-only project or a prototype with no real users can answer
almost none of it and lose nothing; the same project once it's deployed and holding data someone
cares about needs most of it. The two ungated sections — **Concurrency & Write Correctness** and
**Query Efficiency** — apply the moment more than one person uses the app at once, and both are
far cheaper to decide now than to retrofit.

Fill in what you have real answers for. `[TODO]` is fine; a guessed number here is worse than a
blank, because it will get designed against.

## Availability & Recovery

> **Skip unless** someone other than you depends on this app being up, or it holds data that
> would genuinely hurt to lose.

Applies in a light form: the app holds candidate personal data and hiring records, though it is a
portfolio deployment.

- Uptime/availability target: best effort, no SLA (portfolio deployment, one instance per
  environment on Railway's Hobby plan).
- Acceptable planned-maintenance downtime, and when it can happen: [TODO]
- Backup frequency, and how much data loss is tolerable (RPO): Railway's volume backups appear to
  be a Pro-plan feature (a Railway staff answer in their community forum, not in the docs we could
  read), so on the Hobby plan we assume there are **no platform backups** until verified in the
  Railway dashboard. Today both databases hold only demo data. Before any real personal data goes
  in, add scheduled `pg_dump` backups to an S3 bucket or move to a plan with backups. RPO figure:
  [TODO]. Backup of the resume bucket: [TODO]
- How long a full restore may take (RTO), and whether a restore has ever actually been tested:
  RTO [TODO]. One restore must be tested into a scratch database before production go-live —
  an untested backup is not a backup.

## Observability

Distinct from `security.md`'s audit logging: that answers "who changed record X," this answers
"why is the app broken right now."

Always, once the app runs anywhere but your own machine:

- Structured application logging: JSON logs to stdout (collected by Railway, which keeps them
  7 days on the Hobby plan), one line per request with a request id, method, path, status,
  duration, `user_id` and `company_id`. Not emails, names, or any request body. Module:
  `backend/app/logging.py` (`JsonFormatter`, one JSON object per line). The worker uses it today;
  the per-request web log line is still to do.
- A health check endpoint, and what it actually verifies: `GET /health` returns 200 only if the
  process is up **and** the database answers a trivial query; `GET /ready` also confirms
  migrations are at head. The deploy pipeline's smoke test calls `/health`. Neither endpoint
  requires authentication nor reveals versions or internals beyond status.
- Worker liveness: the worker rewrites one `WorkerHeartbeat` row on every pass of its loop (about
  every 2 seconds); `GET /health/worker` returns 200 only if that row is under 60 seconds old, else
  503. Same rules as the other health endpoints: public, status word only.

> **The rest of this section: skip unless** the app is deployed and you'd want to be told it
> broke rather than find out from a user.

Applies (the app is deployed to staging and production), at a minimal level:

- Metrics worth tracking: [TODO]
- Error tracking / alerting: Railway deploy alerts and log inspection only. A hosted error
  tracker (e.g. Sentry) is a possible later addition and would need approval as a new dependency.
  Alert conditions: [TODO]
- Which fields must be redacted or masked in operational logs: that secrets and PII never get
  logged is a given (see `CLAUDE.md` > Security Baseline). Additionally: never log request bodies,
  `Authorization`/cookie headers, resume filenames, or `BackgroundJob.payload` contents beyond ids.

## Environments & Configuration

- Which environments exist (local / staging / production), and how closely staging mirrors prod:
  - **Local:** `docker compose` runs Postgres (on host port 5433, so it cannot clash with a
    Postgres already installed on the machine), plus Mailpit (SMTP catcher, from Phase 3) and
    MinIO (S3 stand-in, from Phase 5); the backend and frontend run on the host. Use
    `127.0.0.1`, not `localhost`, in database URLs: on Windows with Docker Desktop `localhost`
    tries IPv6 first and hangs.
  - **Staging:** one Railway environment (`staging`) with its own Postgres, bucket and secrets;
    deployed automatically on every merge to `main`; seeded demo company so the live app can be
    shown. https://multi-company-ats-staging.up.railway.app
  - **Production:** a second environment (`production`) in the same Railway project, with a
    separate database, bucket and secrets; same container image as staging, deployed only after a
    manual approval. https://multi-company-ats-production.up.railway.app
  - Staging and production run the same image built once; only configuration differs.
- How configuration and secrets differ per environment: All configuration is environment
  variables read in one module (`backend/app/config.py`). Secrets live only in GitHub
  Environments secrets (CI/CD) and Railway variables (runtime) — never in the repo. `.env` is
  git-ignored; `.env.example` lists the variable names. Railway app service variables:
  `DATABASE_URL` (built from the environment's Postgres service with Railway references, using
  the `postgresql+psycopg://` prefix) and `PORT`. GitHub environment secret `RAILWAY_TOKEN` and
  variables `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_ID`, `APP_URL`, set separately on `staging`
  and `production`. `COOKIE_SECURE` (default on, so Railway needs nothing) is the one runtime
  setting that only `.env` changes: it is set to `false` for local development over plain http,
  and must never be set elsewhere. The container starts uvicorn with `--proxy-headers`, so the
  login rate limit sees real client addresses behind Railway's proxy. Full list for later
  phases: [TODO]
- How a release ships, and how it gets rolled back when it's wrong: GitHub Actions
  (`.github/workflows/`). Pull request: lint, type check, backend and frontend tests against a real
  Postgres, migrations applied from scratch, tenant-isolation and role-matrix tests, dependency and
  secret scan, Docker build and image scan. Merge to `main`: build and push the image once, deploy
  to staging, run migrations, smoke-test `/health`, then wait for manual approval, deploy the same
  image to production, migrate, smoke-test. If a production smoke test fails, the pipeline
  redeploys the previous image automatically. Because migrations are backward-compatible (below),
  the old image still works against the new schema. CI provider is GitHub Actions. Deploy
  mechanism: the pipeline builds one image, pushes it to GitHub Container Registry (GHCR) tagged
  with the commit SHA, and points the Railway staging and production services at that tag, so
  rollback is "point back at the previous tag".

  As built (`.github/workflows/deploy.yml`, tooling in `deploy/`): on a push to `main` the jobs
  run in order `checks` (the PR checks again, on the exact commit), `publish`, `deploy-staging`,
  `deploy-production`. A deploy job runs `python -m deploy.release deploy <image>`, which records
  the image currently running, sets the new commit-tagged image through Railway's GraphQL API,
  waits until Railway reports that deployment live, and then smoke-tests the app's public URL
  (`/health`, `/ready`, and the page). Only `main` can deploy: the deploy workflow never runs on
  pull requests, and both GitHub environments accept deployments from `main` only.
  `production` requires a reviewer; the job holds no secrets until it is approved. Each Railway
  token is a project token limited to one environment, kept as the `RAILWAY_TOKEN` secret of the
  matching GitHub environment. If the deploy or smoke test fails, a final step runs
  `deploy.release rollback <recorded image> --worker-image <recorded worker image>`; the job still
  ends red. A manual run with `simulate_smoke_failure` fails a step after a good deploy, to prove
  that rollback.

  Each environment runs two services from the same image: the web service and the background
  worker (`worker`, start command `python -m app.worker`, no health check path, no pre-deploy
  command). A release moves the web service first (migrations run in its pre-deploy command, then
  the smoke test), and only then the worker, so the worker never runs against a schema the web
  service has not migrated. After the worker deployment is live, the pipeline waits until
  `GET /health/worker?deployment=<that deployment's id>` answers 200: the worker writes Railway's
  `RAILWAY_DEPLOYMENT_ID` into its heartbeat, so the previous worker's last heartbeat cannot make a
  crashing new worker look healthy. If anything fails, both services go back to their previous
  images (a worker that never left its old image is not restarted). A rollback target may be an
  image from before the worker reported its deployment, so rolling back checks only that some
  worker is alive. Each GitHub environment holds `RAILWAY_WORKER_SERVICE_ID` next to
  `RAILWAY_SERVICE_ID`.

  Mail in staging and production: a `mailpit` service per environment (image `axllent/mailpit`,
  pinned) catches every email. Its SMTP port is reachable only on Railway's private network
  (`<service name>.railway.internal:1025`, no public TCP proxy); its web inbox has a public domain
  and is protected by `MP_UI_AUTH` (user `ats`, a random password that exists only in that
  service's variables and in a local file, never in git). It is a demo inbox, not a real mail
  service: a real provider replaces it by changing the worker's `SMTP_*` variables. Services are
  named `mailpit`/`worker` in staging and `mailpit-production`/`worker-production` in production
  (Railway requires project-unique service names).
  Railway service settings (set once through its API, per environment): health check path
  `/health` (120 s) and pre-deploy command `alembic upgrade head`. If a new version fails its
  migration or health check, Railway keeps the old one serving. The image package on GHCR is
  public so Railway can pull it without credentials. Railway keeps the image of a removed
  deployment for 72 hours on the Hobby plan, but rollback pulls the previous image again from
  GHCR (which has no such expiry), so a rollback target does not disappear.

## Database Migrations

> **Skip unless** this app is deployed somewhere with data you can't simply recreate. Until
> then, dropping and rebuilding the schema is a legitimate strategy — say so here explicitly, so
> it's a decision rather than an omission.

Applies once staging/production exist (until then, rebuilding locally is fine).

- How schema changes ship: Alembic migrations, backward-compatible (expand/contract). A release
  only adds nullable columns/tables or compatible changes; removing or renaming something takes
  two releases (stop using it, then drop it). Migrations run as Railway's pre-deploy command
  (`alembic upgrade head`) before the new version starts serving; if it fails, the deploy fails.
- Is every migration reversible, and if not, what's the recovery plan? Rollback is "redeploy the
  previous image", not "run a down-migration"; the schema stays at the newer version. Down
  migrations are not required. Recovery from a bad data migration is the database backup.
- How large-table backfills are handled so they don't lock the table or time out: [TODO] (not
  expected at demo scale).
- CI applies the full migration chain to an empty Postgres on every pull request.

## Background Jobs & Queues

> **Skip unless** this app does work outside a request — scheduled tasks, queued jobs, anything
> that keeps running after the response is sent. `performance.md` decides *what* runs async;
> this decides how it behaves when it fails.

Applies: a worker process (hand-written, Postgres-backed; `backend/app/worker/`) sends email and
creates Google Calendar events. It reads the `BackgroundJob` table, claiming rows with
`SELECT ... FOR UPDATE SKIP LOCKED`.

- Retry policy and maximum attempts per job type: Exponential backoff, maximum 5 attempts for all
  job types. Backoff intervals: after a failed attempt 1, 2, 3 and 4 the job waits 1 minute,
  5 minutes, 30 minutes and 2 hours (`JOB_BACKOFF_SECONDS` overrides this, for a local demo only).
- Where permanently-failed jobs go: they stay in `BackgroundJob` with `status = failed` and
  `last_error`. They are surfaced by one ERROR log line when the last attempt fails (job id, type,
  attempt, error class; never the payload or the error text, which may hold an address) and by
  `python -m app.worker status`, which prints job counts by status, the newest failed jobs with
  their reason, and when the worker last checked in. No admin screen in v1.
- Delivery guarantee: at-least-once. Every handler must be idempotent (see `idempotency_key`
  below), so a retry never sends a second email.
- How a stuck or silently-failing job gets detected: a job stuck in `running` past a timeout is
  re-queued (timeout 10 minutes; the lost attempt still counts, so a job that kills its worker
  cannot loop forever); the count of failed and old pending jobs is logged. Alerting on it:
  [TODO]
- Deployment: the worker is its own Railway service in each environment, built from the same
  image as the web service with the start command `python -m app.worker`. Railway stops it with
  SIGTERM on every deploy; it finishes the job in hand and exits with code 0. If the database
  drops, it logs the error and keeps polling. Wiring the service into the pipeline: Phase 3 Step 4.
- Handlers: plain functions `handler(db, job)` registered in `worker/handlers.py`. They never
  commit (the runner commits their changes together with marking the job done) and raise to fail;
  their database changes are rolled back first. A job whose type has no handler is retried, not
  dropped, because during a deploy the web app can be newer than the worker.

## External Integrations

> **Skip unless** this app calls a third-party service — payments, email, storage, maps, an
> internal API owned by someone else.

Applies. Services and their failure behavior:

| Service | Used for | When it is down |
|---|---|---|
| SMTP server (Mailpit inbox on Railway for now; a real provider replaces it by changing the `SMTP_*` variables) | All emails | Jobs retry with backoff; the user action that triggered the email still succeeds |
| Railway storage bucket | Resume files | Upload fails immediately with a clear error; reading a resume shows an error, nothing else breaks |
| Google OAuth | "Continue with Google" | Button shows an error; password login unaffected |
| Google Calendar API | Interview events | Interview is still created and emailed; event creation retries via the worker, then is marked failed |

- Timeout and retry policy per integration — never an unbounded wait: every outbound call sets an
  explicit timeout. Values: SMTP 10 seconds per network step (connect, each command); the other
  integrations set theirs when they are built. Retries only via the background worker, not inline.
- Email settings (environment variables, read by the worker and checked when it starts, so a bad
  value stops it instead of failing every job): `SMTP_HOST`, `SMTP_PORT` (default 587),
  `SMTP_STARTTLS` (default on; off only for the private-network Mailpit), `SMTP_USERNAME` and
  `SMTP_PASSWORD` (optional; refused unless STARTTLS is on), `EMAIL_FROM`, and `APP_BASE_URL`
  (the public address links point at; https required except for localhost).
- Email content: plain text only, built with the standard library; a line break in the subject or
  recipient is refused, so typed text can never add a header. Each email is a `send_email` job:
  the payload names a template and holds ids only; the template (registered in
  `backend/app/emails/`) loads the rest when the worker runs.
- Whether repeated failures trip a circuit breaker: No. The retry cap (5 attempts) is the only
  limit in v1.
- Whether integration failures surface to the user immediately or get queued and retried
  silently: bucket and Google OAuth errors surface immediately (the user is waiting); email and
  calendar failures are retried silently.
- Tests never call real third parties: SMTP goes to Mailpit, storage to MinIO, and Google is
  mocked.

## Concurrency & Write Correctness

The bug class that only appears under real load, and the hardest to retrofit. Applies to any app
where two people can act at the same time — which is nearly all of them.

- Two users editing the same record at once: Optimistic locking with a `version` column on
  `Application` (and `Job`). An update carries the version it was based on; if it no longer
  matches, the write is rejected with a conflict response and the user reloads. Other entities
  are append-only or single-writer.
- Which operations must be idempotent, and what key makes them so:
  - Applying to a job: unique (`candidate_id`, `job_id`); a retry returns the existing
    application.
  - Submitting a scorecard: unique (`interview_id`, `interviewer_id`).
  - Sending an email / creating a calendar event: `BackgroundJob.idempotency_key` (e.g.
    `stage_change_email:<application_id>:<history_id>`).
  - Accepting an invitation / using a token: single-use, enforced with an atomic
    "update where unused" statement.
- Transaction boundaries: each of these is one all-or-nothing transaction —
  company signup (company + admin); apply (application + history + audit + queued emails); stage
  move (stage + version + history + audit + queued email); schedule interview (interview +
  participants + audit + queued jobs); candidate anonymization (user + profile + sessions + file
  records). External effects (email, calendar, deleting the bucket object) happen only after
  commit, through the worker, so a failure there never rolls back the business change.
- Known race conditions in the domain: two recruiters moving or rejecting the same application
  (handled by `version`); a candidate applying while the job is being closed (apply checks job
  status inside its transaction); an interviewer submitting while the recruiter changes the
  assignment (assignment locked once a scorecard exists); last active admin deactivated by two
  admins at once [TODO how enforced].

## Scalability Constraints

> **Skip unless** this app is deployed, or will be. The statelessness rule below is the one to
> read anyway — violating it early is what makes an app impossible to run on more than one
> instance later.

Applies.

- **Statelessness**: app instances hold no session, cache, or upload state in local memory or
  disk. Sessions are in the `Session` table, jobs in `BackgroundJob`, files in the bucket.
- What breaks first as load grows: [TODO]
- Database connection pool sizing, and how it interacts with the number of app instances: [TODO]

## Query Efficiency

Applies from the first list endpoint. These are the defaults that stop a page being fast with ten
rows and unusable with ten thousand.

- How N+1 queries are prevented: explicit eager loading (`selectinload` / `joinedload`) on every
  list endpoint that returns related rows, and an automated test per list endpoint that asserts
  a fixed maximum query count [TODO exact helper].
- Confirm no unbounded queries: every list query takes a limit and offset/cursor, with a hard
  maximum page size, including internal and admin lists.
- Rough query budget for a typical page/endpoint: [TODO]
- Cache invalidation: no caching in v1 (see `performance.md`), so nothing to invalidate yet.

# ATS — multi-company applicant tracking system

Companies publish jobs and run candidates through a fixed hiring pipeline with blind interview
scoring; candidates apply across companies and track their applications. A portfolio project
built to demonstrate CI/CD: every change goes through a GitHub Actions pipeline, and `main` only
accepts pull requests whose checks pass.

- Specification and build plan: [specifications/SPECS.md](specifications/SPECS.md)
- Working conventions: [CLAUDE.md](CLAUDE.md)

## Status

Phases 0 to 3 are done:

- **Phase 0:** a FastAPI backend, a React app, one Docker image that serves both, and the pull
  request pipeline.
- **Phase 1:** deployment. Every merge to `main` goes to staging automatically and to production
  after a manual approval, with automatic rollback.
- **Phase 2:** companies, accounts and tenancy. A company registers and becomes its own isolated
  workspace; its admin invites staff, who log in with a role (admin, recruiter or interviewer);
  admins change roles and deactivate people.
- **Phase 3:** background work and email. A Postgres-backed job queue and a worker process
  (retry with backoff, no duplicate emails, two workers never take the same job) send invitation,
  email-verification and password-reset emails. Links in emails are signed and single-use; a user
  who has not verified their email can log in and nothing else. The worker is deployed and rolled
  back together with the web service, and an hourly job purges old technical rows. Hiring
  features (jobs, applications) start in Phase 4.

- Staging: https://multi-company-ats-staging.up.railway.app
- Production: https://multi-company-ats-production.up.railway.app

## What stops one company seeing another's data

Three automated tests run on every pull request (all in `backend/tests/`), because "company A
can never see company B" is the promise this app must keep:

| Test | Guarantees |
|---|---|
| Route gate | Every route declares who may call it; a route that forgets fails the build. |
| Role x endpoint matrix | Every role is called against every route and must get exactly the answer the written policy says. |
| Tenant isolation | Company A attacks company B's ids on every route and gets "not found", and nothing of B's changes. |

## How a change ships

`.github/workflows/deploy.yml` runs on every merge to `main`:

1. `checks`: the pull request checks again, on the exact commit that will ship.
2. `publish`: builds the Docker image once and pushes it to GitHub's container registry, tagged
   with the commit.
3. `deploy-staging`: points the Railway staging web service at that image, waits until Railway
   says it is live (database migrations run first), then smoke-tests the public URL. Then it moves
   the background worker to the same image and waits until that exact deployment's worker reports
   in.
4. `deploy-production`: waits for a manual approval, then does the same with the same image. If
   anything fails, the previous images of both services are restored automatically and the run is
   marked failed. A rollback works even after a release that added a database migration.

After a release, an hourly workflow (`.github/workflows/monitor.yml`) keeps watching both
environments: it fails, and GitHub sends an email, if the background worker stops reporting in or
a job gives up after its retries.

The deploy tooling lives in [deploy/](deploy/) and is tested like the app.

> Staging and production send email to a password-protected demo inbox (Mailpit), not to real
> addresses. A real mail provider replaces it by changing the worker's `SMTP_*` variables, and is
> needed before real users.

## What the pipeline checks

Every pull request runs four jobs in parallel (`.github/workflows/pr.yml`); all must pass:

| Job | Runs |
|---|---|
| `backend` | Ruff, mypy, migrations applied to an empty Postgres, pytest |
| `frontend` | ESLint, Prettier, TypeScript, Vitest, production build |
| `security` | gitleaks over the full history, `pip-audit`, `npm audit` |
| `image` | Docker build, then a Trivy scan that fails on fixable HIGH/CRITICAL findings |

## Run it locally

Needs Docker, Python 3.14 and Node 26.

```bash
# 1. Settings: copy the example, then edit the password if you like (.env is git-ignored)
cp .env.example .env

# 2. Postgres on 127.0.0.1:5433, and Mailpit (catches emails; inbox at http://127.0.0.1:8025)
docker compose up -d --wait

# 3. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows. On macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
```

The backend reads its settings from environment variables and does not load `.env` itself, so
load the file into your shell first:

```bash
# bash / Git Bash
set -a; . ../.env; set +a
```

```powershell
# PowerShell
Get-Content ..\.env | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] } }
```

```bash
alembic upgrade head                # create the schema
uvicorn app.main:app --reload       # API on http://127.0.0.1:8000  (try /health and /ready)
python -m app.worker                # background worker, in another terminal (Ctrl+C stops it)
python -m app.worker status         # job counts by status, failed jobs, when the worker last ran

# 4. Frontend, in a second terminal
cd frontend
npm ci
npm run dev                         # http://127.0.0.1:5173, forwards /health, /ready and /api to the backend
```

Run the checks the pipeline runs (backend commands from `backend/` with the environment loaded):

```bash
ruff check . && ruff format --check . && mypy && pytest
npm run lint && npm run format:check && npm run typecheck && npm test      # in frontend/
```

Run the production image, which serves the API and the built page on one port:

```bash
docker build -t ats .
docker run --rm -p 127.0.0.1:8000:8000 \
  -e DATABASE_URL=postgresql+psycopg://<user>:<password>@host.docker.internal:5433/<db> ats
```

Stop the database with `docker compose stop`; `docker compose down -v` also deletes its data.

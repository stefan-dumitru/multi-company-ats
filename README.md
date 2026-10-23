# ATS — multi-company applicant tracking system

Companies publish jobs and run candidates through a fixed hiring pipeline with blind interview
scoring; candidates apply across companies and track their applications. A portfolio project
built to demonstrate CI/CD: every change goes through a GitHub Actions pipeline, and `main` only
accepts pull requests whose checks pass.

- Specification and build plan: [specifications/SPECS.md](specifications/SPECS.md)
- Working conventions: [CLAUDE.md](CLAUDE.md)

## Status

Phase 0 is done: a small FastAPI backend (`/health`, `/ready`), a React page that shows whether
the backend is healthy, one Docker image that serves both, and the pull request pipeline. Hiring
features start in Phase 2. Deployment (staging and production) is Phase 1.

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

# 2. Database (Postgres on 127.0.0.1:5433)
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

# 4. Frontend, in a second terminal
cd frontend
npm ci
npm run dev                         # http://127.0.0.1:5173, forwards /health to the backend
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

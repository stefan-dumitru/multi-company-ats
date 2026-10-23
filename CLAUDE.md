# CLAUDE.md

Durable conventions for this project. Auto-loaded into every session, so it stays short —
anything long or feature-specific belongs in [specifications/](specifications/SPECS.md), which is
read selectively.

Sections marked `[TODO]` are filled in per project. Everything else is a default that applies
unless this file says otherwise.

---

## Project

- **What this is:** A multi-company applicant tracking system (ATS): companies publish jobs and
  run candidates through a fixed hiring pipeline with blind interview scoring; candidates apply
  across companies and track their applications. It is also a CI/CD portfolio project: the
  GitHub Actions pipeline and the automated tenant-isolation / authorization tests are
  deliverables, not extras.
- **Full specification:** [specifications/SPECS.md](specifications/SPECS.md) (build phases are
  listed there under "Build Phases")

## Stack

- **Language / runtime:** Python 3.14 (backend); TypeScript on Node 26 (frontend build only).
  Pin these exact versions in the Dockerfile and in CI so they match local. If a library lacks
  Python 3.14 support, tell me rather than silently downgrading.
- **Code quality tools:** Ruff and mypy (Python); ESLint and Prettier (frontend). Approved.
- **Frontend:** React single-page app, Tailwind CSS + shadcn/ui, served from the same origin as
  the API.
- **Backend:** FastAPI, SQLAlchemy, Alembic. Hand-written Postgres-backed background worker (no
  Redis/Celery). Dependencies managed with pip + venv + pinned `requirements.txt`.
- **Database:** PostgreSQL. Resume files in an S3-compatible bucket (Railway bucket in
  staging/production, MinIO locally and in CI).
- **Hosting / CI/CD:** Railway (staging + production), GitHub Actions. Docker.
- **Testing:** pytest (backend); Vitest + React Testing Library (frontend); Playwright
  (end-to-end, post-deploy).

## Commands

Fill these in as soon as they exist, and delete any row this project doesn't have. Use these
rather than guessing an equivalent, and tell me if one is missing instead of inventing a
workaround.

None of these exist yet: the project has no code. The entries below are what Phase 0 is expected
to create. Verify and correct each one when it first runs.

| Purpose | Command |
|---|---|
| Install dependencies | `pip install -r backend/requirements.txt` (inside a venv); `npm --prefix frontend ci` |
| Run in development | `docker compose up -d` (Postgres, MinIO, Mailpit); `uvicorn app.main:app --reload` from `backend/`; `npm --prefix frontend run dev` |
| Run tests | `pytest` from `backend/`; `npm --prefix frontend test`; end-to-end: `npx playwright test` from `frontend/` |
| Run a single test file | `pytest tests/<file>.py` from `backend/`; `npm --prefix frontend test -- <file>` |
| Lint / format | `ruff check backend` and `ruff format --check backend`; `npm --prefix frontend run lint` and `npm --prefix frontend run format:check` |
| Type check | `mypy backend/app`; `npm --prefix frontend run typecheck` |
| Build for production | `docker build -t ats .` (builds the frontend and the backend into one image) |
| Database migration | `alembic upgrade head` from `backend/`; new migration: `alembic revision --autogenerate -m "<message>"` |

## Project Structure

Planned layout (nothing is created yet):

- `backend/app/` — FastAPI app. `routers/` (HTTP layer only), `services/` (business rules and
  tenant-scoped data access), `models/` (SQLAlchemy), `schemas/` (request/response models),
  `auth/` (sessions, permissions, Google OAuth), `worker/` (background job loop and handlers),
  `integrations/` (SMTP, S3, Google Calendar), `config.py`.
- `backend/alembic/` — migrations. `backend/tests/` — pytest, including the tenant-isolation and
  role x endpoint tests.
- `frontend/src/` — React app; `frontend/e2e/` — Playwright tests.
- `.github/workflows/` — `pr.yml` (checks on pull requests) and `deploy.yml` (staging, then
  production with manual approval and rollback).
- `Dockerfile`, `docker-compose.yml`, `.env.example` — packaging and local services.
- `specifications/` — the spec files; read selectively (see SPECS.md).

---

## How We Work

My experience level: beginner-to-intermediate Python developer; I'm here to understand the code,
not just receive it. I am new to CI/CD, React and multi-tenant design, so explain those parts
more; keep the Python conventional.

- **Plan before building.** For anything beyond a small edit, use Plan Mode first. Read the
  relevant `specifications/` file(s), propose an approach, and wait for my review before writing
  code.
- **Ask instead of assuming.** If a requirement is ambiguous and two readings would produce
  materially different code, ask. Don't guess and don't build both.
- **No new dependencies without asking first.** Name the library, what it's for, and what the
  alternative is without it.
- **Stay in scope.** Build what was asked. If you spot an unrelated problem, mention it — don't
  fix it in the same change.
- **Work in small, verifiable steps.** Prefer a working slice I can run over a large change I have
  to take on faith. For multi-step work, state the steps up front and stop at the end of each one.
- **Explain non-obvious decisions.** A one-line comment or a sentence in your reply. Not a tutorial
  on the obvious parts.
- **Keep specs in sync.** When a feature reveals a spec file is wrong or incomplete, update that
  file as part of the same work — not as cleanup later.
- **Report honestly.** If tests fail, show the output. If something is unverified, say so. "Done"
  means written, run, and checked.

## Definition of Done

A change is finished when all of these hold:

1. It does what was asked, and nothing extra.
2. It runs — verified by actually executing it, not by inspection.
3. Tests for the new behavior exist and pass, and the existing suite still passes. The exception
   is a spike or throwaway we've agreed is exploratory — say so out loud rather than quietly
   skipping this.
4. Lint / type check / format are clean.
5. Errors and empty states are handled, not just the happy path.
6. Any spec file the change contradicts has been updated.

## Code Style

- **Clear over clever.** Conventional, readable code beats a compact abstraction. If a junior dev
  would need to pause and work out what a line does, write the longer version.
- **Don't abstract early.** Duplication is cheaper than the wrong abstraction. Extract on the third
  use, not the first.
- **Match surrounding code.** Naming, file layout, and comment density should follow what's already
  in the file over any general preference here.
- **Name things for what they mean,** not what type they are. `unpaidInvoices`, not `dataArray`.
- **Handle errors where you can act on them.** No empty catch blocks, no swallowed failures.
- **Comment the why, not the what.** The code says what it does; comments explain why it's done
  that way.
- **Functions do one thing.** If you need "and" to describe it, it's two functions.
- **Store every timestamp in UTC,** regardless of where users are. Convert for display only.
  Mixing zones at the storage layer is nearly impossible to untangle later.
- **Project-specific conventions:**
  - **Tenant scoping is mandatory.** Every query on a company-scoped table goes through a
    service function that takes the current user and filters by company (and by assignment for
    recruiters and interviewers). Never query such a table directly from a router.
  - **Every route declares a permission.** A route without one fails the CI test.
  - **Return "not found", not "forbidden",** for rows outside the caller's scope.
  - **Business change and its side effects are one transaction:** the change, the history/audit
    rows, and the queued `BackgroundJob` all commit together. Emails and calendar calls happen
    in the worker, never inside a request.
  - **Transactional data is append-only** (history, notes, audit log, scorecards): no edit or
    delete endpoints unless the spec says so.
  - **Migrations must be backward-compatible:** no drop or rename in the same release that
    stops using the column.

## Testing

- Write tests alongside the code, not as a later pass — the change isn't done until both exist.
  Where the expected behavior is already written down (the "Rules & edge cases" in a use case),
  write the test first.
- Derive a test from what the code *should* do, not from what it does. Reading a finished
  function and asserting its current output encodes the bug as the requirement.
- Cover the **behavior**, not the implementation — a test that breaks on every refactor is a
  liability.
- For each unit of logic: the expected case, the boundaries, and the failure case.
- Test what's genuinely yours. Don't write tests that only prove the framework works.
- A bug fix starts with a test that reproduces the bug and fails.
- Never weaken or skip a test to make a suite pass. A failing test is information — bring it to me.

## Security Baseline

Non-negotiable defaults for every project. App-specific requirements (auth model, compliance
scope, data sensitivity) live in [specifications/security.md](specifications/security.md).

- **Validate all input server-side,** at the boundary where it enters the system. Client-side
  validation is a convenience for the user, never a control.
- **Default-deny authorization.** Every endpoint requires an explicit check that this user may
  perform this action on this record. Absence of a rule means denied, not allowed.
- **No secrets in code** — no keys, passwords, tokens, or connection strings in source or in git.
  Environment variables or a secrets manager, and `.env` stays in `.gitignore`.
- **Parameterized queries only.** Never build SQL by string concatenation.
- **Hash passwords** with a strong, slow algorithm (bcrypt/argon2). Never store or log them in
  plaintext.
- **Escape user content on output** before it reaches HTML or the DOM.
- **Don't leak internals in error responses.** Generic message to the client, full detail to the
  server log.
- **Never log secrets or PII.**
- **HTTPS everywhere.** No credentials, tokens, or user data over plain HTTP, in any environment.
- **Never trust an uploaded filename.** Generate the stored path yourself; the original name is
  display metadata only. Authorize the upload *before* writing the file, not after.

## Git Conventions

- **Branch per change:** `feature/<short-name>`, `fix/<short-name>`; `chore/<short-name>` for
  CI, tooling and dependency changes. The project is not a git repository yet: `git init` is part
  of Phase 0, and I'll ask before doing it.
- **Commit messages:** imperative mood, subject under ~70 characters, explaining *why* in the body
  when the change isn't self-evident. e.g. `Add stock check before checkout`.
- **One logical change per commit.** Don't mix a refactor with a feature.
- **Never commit or push unless I ask.** Never force-push, never rewrite shared history, never
  commit directly to the default branch.
- **Never commit** secrets, `.env` files, build output, or dependency directories.

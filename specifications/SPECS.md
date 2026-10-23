# Specifications — Index

This folder holds the specification for what you're building. Durable, cross-project conventions
(coding style, git conventions, security baseline) live in [../CLAUDE.md](../CLAUDE.md) instead —
that file is auto-loaded every session, this folder is read selectively.

Specs are split by concern so you can update one without touching the others, and so you can hand
Claude only the file(s) relevant to the feature you're working on rather than the whole document.

| File | Covers |
|---|---|
| [functional.md](functional.md) | Product overview, user roles, use cases / user stories, in/out of scope |
| [data-model.md](data-model.md) | Entities, master data vs. transactional data, relationships |
| [ui-guidelines.md](ui-guidelines.md) | Design system, branding, key flows, accessibility |
| [security.md](security.md) | Auth/authz model, data protection, compliance, threat model |
| [performance.md](performance.md) | Response time targets, scale expectations, caching, pagination, frontend budget |
| [operations.md](operations.md) | Availability, observability, migrations, background jobs, integrations, concurrency, scaling constraints |

## Two rules these files follow

**Invariants live in `CLAUDE.md`, decisions live here.** Anything true of every project — use
parameterized queries, hash passwords, authorize before acting — belongs in `CLAUDE.md`, which is
loaded every session. These files hold only what varies per app. Where a spec file needs to
mention an invariant for context, it states it as a given and points at `CLAUDE.md` rather than
restating the rule. A rule written as a `[TODO]` reads as optional, which is exactly wrong.

**Sections are gated.** A section headed with a `> **Skip unless** …` blockquote doesn't apply to
every project. The trigger is always something concrete you can check — "this app accepts file
uploads," not "the project is complex." Skipping a gated section is free; skipping an ungated one
is a decision you should make deliberately.

## How to use this per project

1. Copy this whole repo (`CLAUDE.md` + `specifications/`) as the starting point for a new app.
2. Fill in `first-prompt.md` and give it to Claude. It reads these files, interviews you, and
   fills them in — you don't fill them by hand first. Answer "I don't know" freely; it becomes a
   `[TODO]`, which is always better than a guess baked in early.
3. Review what it wrote. This is the step that matters — the interview surfaces decisions, but
   they're still yours. Anything left `[TODO]` is a question you can come back to.
4. Start building. For each feature: open Plan Mode, point Claude at the relevant spec file(s),
   review the plan, then build. Don't try to resolve every `[TODO]` before writing any code —
   for a complex app you will discover requirements while building, not before.
5. When a feature reveals the spec was wrong or incomplete, update the spec file as part of that
   feature's work, not as separate cleanup later.

## Optional Extensions

Not created by default — add these only when a feature or the project's size genuinely needs them:

- **`pages/<page-name>.md`** — a full spec for one screen (layout per breakpoint, interactions,
  API calls, state, error states) when that screen is complex enough that Plan Mode alone risks
  missing something. See `ui-guidelines.md` > Per-Screen Specification Files.
- **`features/<feature-name>.md`** — a full spec for one complex feature's business rules (e.g. a
  multi-mode import/export process), when the rules have enough edge cases that they don't fit
  cleanly as a `functional.md` use case. See `functional.md` > Use Cases.
- A phased, dated implementation plan with milestones and sign-off is a reasonable choice for a
  larger team or a client-facing project with formal checkpoints — it trades the iterative
  approach's flexibility for more upfront predictability. This template defaults to iterative
  because that trade usually isn't worth it for a solo/AI-assisted build, but it's a legitimate
  choice when made deliberately, not a mistake.

## Build Phases

Smallest useful slice first, each phase merged and deployed through the pipeline before the next
starts. "Automated tests" is what the phase must ship with; "Check yourself" is the end-to-end
check you can run to confirm it works. Directory names refer to `CLAUDE.md` > Project Structure.

The pipeline comes first on purpose: every later phase then lands through CI/CD from day one.

| # | Phase | Automated tests | Check yourself |
|---|---|---|---|
| 0 | **Skeleton + PR pipeline.** Repo layout; FastAPI app with `GET /health` (DB reachable) and `/ready`; Alembic set up with an empty first migration; React + Vite shell calling `/health`; Dockerfile; `docker-compose.yml` (Postgres, MinIO, Mailpit); `.github/workflows/pr.yml` running lint, type check, backend and frontend tests against a real Postgres, migrations from scratch, dependency/secret scan, image build and scan | `/health` ok and failing when DB is down; migrations apply to an empty DB; one frontend smoke test | Open a PR: all checks pass. Break a test on purpose: the PR is blocked. `docker compose up` then the app shows "healthy" |
| 1 | **Deploy pipeline.** `.github/workflows/deploy.yml`: build image once, deploy to Railway staging on merge to `main`, run migrations, smoke-test `/health`; production behind a GitHub Environment manual approval; automatic rollback to the previous image on a failed smoke test | Smoke-test script (success and failure paths); a deliberately broken release proves the rollback | Merge a change: staging updates. Approve: production updates. Merge a build whose `/health` fails: the previous version is restored |
| 2 | **Companies, auth and tenancy.** Company signup, email+password login, `Session` table and cookie, CSRF protection, `User` and `Invitation` (invitation link shown to the admin until email exists), roles, deactivation, `require_permission` and tenant-scoped data access, route-permission test | Password hashing and session rules; tenant-isolation test; role x endpoint matrix; every route has a permission; idle timeout; deactivated user blocked | Register company A and B in two browsers: neither sees the other. A recruiter gets "not found" on an admin URL |
| 3 | **Background worker and email.** `BackgroundJob` table, worker loop with `SKIP LOCKED`, retry/backoff, idempotency key; SMTP sender; invitation, email verification and password reset emails | Retry/backoff and max-attempts; idempotency (no duplicate email); two workers never take the same job | Invite a user in local dev: the email appears in Mailpit. Stop the SMTP service: the job retries, then shows `failed` |
| 4 | **Departments and jobs.** `Department`, `Job`, `JobRecruiter`, job status flow, candidate-facing job list and detail with full-text search | Status transitions; recruiter sees only assigned jobs; search ranking; closed/draft jobs hidden from candidates; pagination | Create jobs as a recruiter; a second recruiter does not see them until assigned; an anonymous visitor finds an open job by keyword |
| 5 | **Candidates, resume and apply.** Candidate registration, `CandidateProfile`, resume upload to the bucket (`File`), apply with resume snapshot, "my applications" list, withdraw/reactivate | Upload validation (type by content, size limit, generated key); apply is idempotent; unique constraint; withdraw/reactivate rules; candidate cannot see others' data | As a candidate on a phone-size window: upload a resume, apply, see "Applied", withdraw. Second company cannot read the resume |
| 6 | **Pipeline and audit log.** Stage moves, rejection with reason, `ApplicationStageHistory`, `Note`, `AuditLog`, optimistic locking, candidate emails on application and stage change | Transition rules; concurrent-move conflict test; history and audit written atomically; notes hidden from candidates and interviewers | Open one application in two windows: advance in one, then try to reject in the other and see the conflict message |
| 7 | **Interviews and scorecards.** `Interview`, `InterviewParticipant`, `Scorecard`, blind scoring, interviewer views, interview emails, Google Calendar connection and event creation (mocked in tests) | Blind scoring (API hides others until own submitted); one scorecard per interviewer; calendar failure does not block scheduling; interviewer sees only assigned interviews | Two interviewers on one interview: neither sees the other's scorecard until submitting. Schedule with a connected Google account: the event appears |
| 8 | **Google login.** OAuth sign-in for candidates, account linking rules | Linking only when both emails verified; unknown email creates a candidate; deactivated user refused | Sign in with Google on a fresh and on an existing account |
| 9 | **Talent pool.** Opt-in flag, recruiter search over discoverable candidates, anonymized candidates excluded | Only opted-in, non-anonymized candidates returned; opting out removes them at once; tenant rules still hold | Opt in as a candidate, find them as a recruiter at another company, opt out, they disappear |
| 10 | **Analytics dashboards.** Funnel, open jobs and application volume, rejection reasons, scoped per role | Counts correct against fixtures; recruiter sees only assigned jobs; no cross-tenant counts | Dashboard numbers match what you can count by hand in the application list |
| 11 | **Demo seed, end-to-end tests, candidate account deletion and data export.** Seeded demo company on staging; Playwright end-to-end run against staging after each deploy; anonymization and export | Anonymization (PII gone, history kept); export contains only the caller's data | The pipeline's Playwright job passes on staging; delete a test candidate and confirm the recruiter now sees "Deleted candidate" |

Phases 8 to 10 are the scope added during planning; they come after the core flow is deployed so
the core cannot be starved by them.

### Dependencies that need approval before use

Per `CLAUDE.md`, none of these is installed until you approve it when its phase starts. Already
fixed in the brief: FastAPI, PostgreSQL, SQLAlchemy, Alembic, React, Tailwind CSS, shadcn/ui,
pytest, Vitest, React Testing Library, Playwright, Docker, GitHub Actions.

- Python: password hashing library, S3 client (proposed: boto3), Google OAuth / API client,
  application-level encryption library, HTTP test client, SMTP client, login rate limiter.
- Frontend: router, data-fetching library, form library.

Approved already: Ruff, mypy (Python); TypeScript, ESLint, Prettier (frontend). Python 3.14 and
Node 26 are pinned; a library without Python 3.14 support gets flagged to you before any
workaround.

## What's deliberately *not* here

- **Execution / Testing / Deployment** aren't spec sections in this template. They're workflow —
  they happen via the plan → build → test → commit loop per feature (and CI/deployment config
  once you have one), not a document you write once upfront. Trying to spec "testing" in the
  abstract before any code exists tends to produce boilerplate that doesn't match what the app
  actually needs tested. The standing rules for how testing is done live in `CLAUDE.md` >
  Testing; what "finished" means is `CLAUDE.md` > Definition of Done.
- **Design of individual screens/modules** isn't a separate phase either — it happens inside Plan
  Mode for the feature that needs it, informed by `ui-guidelines.md` and `data-model.md`. Only the
  durable, cross-feature design decisions (design system, branding, overall IA) belong in
  `ui-guidelines.md`.

Problem & audience: A multi-company applicant tracking system (ATS). Companies
(tenants) need one place to publish jobs, move candidates through a hiring
pipeline, run interviews with fair scoring, and keep a record of every hiring
decision. Candidates need one place to apply to jobs at different companies and
see where each application stands. Audience: small and mid-size companies with
no dedicated HR software, and job seekers applying to them. This is also a
portfolio project: it must demonstrate a real CI/CD pipeline (see Stack &
constraints).

Task: Version 1 is a single fixed hiring flow, end to end.
- Company admin:
  - Manages their company's users (invite, deactivate, assign role).
  - Manages departments.
  - Can see every job and application in their company.
- Recruiter:
  - Creates and edits jobs (title, department, location, description,
    status: draft / open / closed).
  - Reviews applications for jobs they are assigned to.
  - Moves an application through the fixed pipeline: Applied -> Screening ->
    Interview -> Offer -> Hired, or Rejected from any stage (with a reason).
  - Schedules interviews and assigns interviewers.
  - Adds internal notes to an application.
- Interviewer:
  - Sees only the interviews assigned to them, with the candidate's profile and
    resume.
  - Submits a scorecard (overall rating, per-criterion ratings, written
    feedback, recommendation).
  - Blind scoring: cannot see other interviewers' scorecards until they have
    submitted their own.
- Candidate:
  - Has one global account, not tied to any company.
  - Maintains a profile (name, contact details, resume upload).
  - Applies to open jobs at any company.
  - Sees the status of each of their applications, and can withdraw one.
- Every change to an application (stage move, rejection, scorecard, note) is
  written to an audit log: who, what, old value -> new value, when.
- Key flows: candidate applies -> recruiter screens and advances ->
  interviewers score (blind) -> recruiter decides (offer, hire, or reject).

Roles & access: Four roles in v1.
- Company admin: their own company only.
- Recruiter: only the jobs they are assigned to (and those jobs' applications).
- Interviewer: only the interviews assigned to them.
- Candidate: only their own profile and applications, across all companies.
Every company-scoped record belongs to exactly one company, and no company user
can ever see another company's data. Users sign up and log in inside this app
(no SSO). Company users join by invitation from their company admin. Candidates
self-register. Open question for the interview: how a new company gets created
in v1, given the platform super-admin role is out of scope.

Stack & constraints:
- Python, FastAPI, PostgreSQL, SQLAlchemy + Alembic migrations, Docker.
- Frontend: undecided between server-rendered (Jinja + HTMX) and React. Raise
  this in the interview and recommend one. I am beginner-to-intermediate with
  Python.
- Hosting: undecided. Prefer a free or low-cost platform that supports Docker
  and a managed Postgres.
- Background work (emails) should use a Postgres-backed worker, not a new
  service such as Redis or Celery, unless there is a strong reason.
- CI/CD is a first-class requirement, not an afterthought. GitHub Actions
  pipeline that, at minimum:
  - On every pull request: lint, type check, tests against a real Postgres,
    migrations applied from scratch, dependency/secret scan, Docker build and
    image scan.
  - As CI gates: an automated tenant-isolation test (company A can never read
    or write company B's data) and a role x endpoint authorization test that
    fails if a route has no permission rule.
  - On merge to main: deploy to staging automatically, run migrations, run a
    smoke test against /health.
  - Production deploy behind a manual approval, with automatic rollback if the
    smoke test fails.
  - A seeded demo company on staging so the live app can be shown to recruiters.
- Off-limits: no secrets in the repo, no new dependencies without asking.

Non-goals:

- No hiring manager role. Recruiters make the hiring decisions in v1.
- No configurable pipeline templates. The stages are fixed.
- No offer-approval workflow or generated offer letters. "Offer" is a stage,
  not a document.
- No custom email templates. Emails use fixed built-in text.
- No video-call links.

---

Before asking me anything, read CLAUDE.md and every file in specifications/.
They tell you what needs filling in and which questions are worth asking.

Then interview me with AskUserQuestion, working through the spec files in this
order: functional.md, data-model.md, ui-guidelines.md, security.md,
performance.md, operations.md. Finish with a short pass on CLAUDE.md's Stack
and Commands — the test runner in particular, since that's a dependency you
shouldn't pick for me.

During the interview:
- Respect the gates. A section headed "Skip unless <trigger>" only applies if
  that trigger is actually true of this app. Check the trigger, and if it
  doesn't fire, skip the whole section and leave it in place unfilled — don't
  ask me its questions and don't delete it. If you can't tell whether a trigger
  fires, that one question is worth asking.
- Dig into the hard parts I probably haven't considered — concurrent writes to
  the same record, what happens to in-flight work when referenced data changes,
  delete and cascade behavior, where files are stored, how roles map onto
  accounts. The spec templates flag many of these; use them.
- Skip anything I've already answered above, and anything CLAUDE.md settles.
- "I don't know" and "no opinion" are valid answers. Record them as [TODO].
  Never invent a number, a target, or a policy on my behalf — a guess in a spec
  gets designed against, a [TODO] gets asked about.
- Batch related questions rather than asking one at a time. Aim for roughly
  6-10 rounds. Before your final round, show me a short list of what's still
  unresolved and let me decide what actually matters.

Then write the spec:
- Fill in the existing files under specifications/ in place. Don't create new
  spec files unless a feature or screen genuinely warrants one (see SPECS.md >
  Optional Extensions), and don't write a separate combined spec document.
- Fill in CLAUDE.md's Project, Stack, Commands, and Project Structure sections.
- Leave [TODO] wherever I didn't have an answer.
- Name the actual files, modules, and interfaces involved — not just concepts.
- Break the build into phases, smallest useful slice first. For each phase,
  name two things: what gets automated tests, and the end-to-end check I can
  run myself to confirm the phase works.

Then stop. Don't write application code until I've reviewed the spec and told
you to start.

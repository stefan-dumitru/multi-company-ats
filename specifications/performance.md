# Performance Requirements

Only fill in numbers you actually care about. A vague "should be fast" gives Claude nothing to
design against — a target latency or load figure does. Leave `[TODO]` rather than guessing.

Stance for v1: portfolio/demo scale. The goal is correct behavior and sensible habits
(pagination, indexes, no N+1), not tuning. No latency or load numbers were given, so none are
set here.

## Response Time Targets

| Operation | Target (p50) | Target (p95) | Notes |
|---|---|---|---|
| Page load / initial render | [TODO] | [TODO] | |
| API read (simple) | [TODO] | [TODO] | |
| API write | [TODO] | [TODO] | |
| Job full-text search | [TODO] | [TODO] | Postgres `tsvector` + GIN index |
| Analytics dashboard | [TODO] | [TODO] | Aggregations over `Application` and `ApplicationStageHistory` |

## Scale Expectations

- Expected concurrent users at launch / at 1 year: Portfolio/demo scale, tens of users. Numbers
  [TODO]
- Expected data volume (rows in largest tables, growth rate): Thousands of rows. Numbers [TODO]
- Read/write ratio, if lopsided: [TODO]
- Any known spiky load pattern: [TODO]

## Constraints This Implies

- Pagination required on: every list endpoint — jobs, applications, talent pool results, users,
  interviews, notes, audit log. Default and maximum page size: [TODO]
- Caching — what gets cached and for how long: Nothing in v1. Revisit only if a measured
  problem appears (dashboard aggregates are the likely first candidate). Any cache added later
  needs a TTL and an invalidation rule in `operations.md` > Query Efficiency.
- Background/async processing needed for: sending email, creating Google Calendar events, and
  purging expired sessions/jobs. Anything that calls a third party runs through the worker, never
  inside the request (see `operations.md` > Background Jobs & Queues).
- Database indexing priorities (derived from `data-model.md` query patterns):
  - Foreign keys used for scoping: `Application(company_id, job_id)`, `Application(candidate_id)`,
    `Job(company_id, status)`, `JobRecruiter(user_id)`, `InterviewParticipant(interviewer_id)`.
  - `Job.search_vector` GIN index for full-text search.
  - Unique indexes: `User(lower(email))`, `Application(candidate_id, job_id)`,
    `Scorecard(interview_id, interviewer_id)`, `BackgroundJob(idempotency_key)`.
  - `BackgroundJob(status, run_at)` for the worker's polling query.
  - `ApplicationStageHistory(application_id, changed_at)` for the funnel/time queries.
- Debounce interval for search/filter inputs that trigger an API call: [TODO]

## Frontend Performance Budget

> **Skip unless** this app has a browser frontend. If it does, this section is not optional —
> everything above is server-side, and users judge "fast" almost entirely by what happens in the
> browser.

Applies (React SPA). No budget was set in the interview.

- Initial JS/CSS bundle size budget: [TODO]. Once chosen, the CI pipeline should fail the build
  when the budget is exceeded.
- Core Web Vitals targets (LCP, INP, CLS): [TODO]
- Image strategy: [TODO]
- Font loading strategy, if using custom fonts: [TODO]

## Bulk / File Operation Performance

> **Skip unless** this app imports, exports, or otherwise processes files or bulk records —
> the same trigger as `data-model.md` > Bulk Operations.

(Skipped: no import, export or bulk processing in v1. Resume upload is a single 5 MB-capped file
per request; see `security.md` > File Upload Handling.)

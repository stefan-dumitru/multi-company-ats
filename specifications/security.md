# Security Requirements

The project-wide default posture (validate input, no secrets in code, default-deny authz) is in
[../CLAUDE.md](../CLAUDE.md) and applies regardless of what's filled in below. This file is for
requirements specific to *this app* — its data sensitivity, its auth model, its compliance scope.

## Data Sensitivity

- What's the most sensitive data this app stores: Personal data of job seekers (name, email,
  phone, location, resume files) and hiring evaluations about them (scorecards, internal notes,
  rejection reasons). No payment or health data.
- Any regulatory scope: GDPR-aware, with no formal certification. In practice: account deletion
  by anonymization, an explicit opt-in for the talent pool, a data export for candidates, and a
  retention policy (period [TODO]). Not claiming GDPR compliance as a whole.

## Authentication

Which identity source this app uses is in `functional.md` > Authentication & Identity Source.
This section covers how it's implemented and how it fails.

- If login is local: method: Email + password, with email verification. Google OAuth as an
  additional method (Phase 8). Password hashing: bcrypt or argon2 per `CLAUDE.md`; library:
  `argon2-cffi` (Argon2id). Password rules: minimum 12 and maximum 128 characters, no composition
  rules (length over symbols). Login is rate-limited per account and per IP: 5 failed attempts per
  email and 20 per IP within 15 minutes, then HTTP 429 until the window passes. Failures are kept
  in `LoginAttempt` (email stored hashed); unknown emails count too, so the lockout reveals
  nothing; a successful login clears that email's failures. The client address comes from the
  platform proxy (`--proxy-headers`).
- Session handling: Server-side sessions stored in the `Session` table, referenced by an opaque
  random token in an httpOnly, Secure, SameSite cookie. The SPA is served from the same origin as
  the API, so there is no CORS and no token in JavaScript. State-changing requests require a CSRF
  header: the session cookie is SameSite=Lax, and every state-changing request must echo a per-session
  CSRF token (synchronizer token: stored on the session, returned by login and `GET /api/auth/me`,
  sent back in the `X-CSRF-Token` header, compared in constant time). Idle timeout: 30 minutes for
  staff roles, 7 days for candidates. Absolute lifetime: 12 hours for staff, 30 days for
  candidates. The cookie is `ats_session`; `COOKIE_SECURE=false` (local development only) is the
  one way to turn off its Secure flag. Sessions are revoked on deactivation, password change and
  account deletion.
- MFA required: No (non-goal for v1).
- If the identity comes from an external provider (Google): an unknown Google email creates a
  candidate account, never a staff account. An existing account is linked only if Google reports
  the email as verified and the existing account's email is verified too; otherwise refuse and
  ask the user to log in with the password first. A deactivated or anonymized user cannot sign in
  by any method. Whether staff may use Google at all: [TODO]
- Password reset: `POST /api/auth/forgot-password` answers `202` with the same words for every
  address (known, unknown, deactivated) and sends a link only to an active account, at most 3
  links per hour per account (silently, so the limit cannot be used to probe). `POST
  /api/auth/reset-password` takes the signed link and the new password: the password rules are
  checked first (a weak password does not use up the link); the link is then used by one atomic
  UPDATE; then, in one transaction, the new argon2 hash is stored, every session is revoked, other
  reset links are voided, the login lockout is cleared, an unverified address becomes verified
  (the link proved the inbox), an audit row is written (no secrets) and a "your password was
  changed" email is queued. The link never logs anyone in.
- Unverified accounts: a user whose email is not verified can log in and use only their own
  account (`ACCOUNT_SELF`: who am I, log out, resend the link). Every other permissioned route
  answers `403` with `code: email_not_verified`; the check runs inside `require_permission`, after
  the role check (a route a role could never use does not hint "verify"), so no route can forget
  it, and the role x endpoint matrix has an "unverified" dimension that proves it route by route.
  Resending is limited to 3 links per hour per user so it cannot flood an inbox.
- Invitations and email-verification/reset links: single-use, expiring (invitation 7 days, email
  verification 24 hours, password reset 1 hour), and **signed, not stored**: a link is
  `<row id>.<HMAC-SHA256(SECRET_KEY, purpose:row id)>`. An email needs the real link but the job
  queue must hold no secrets, so the queue holds only the row id and the worker rebuilds the link
  when it sends; nothing secret sits in the queue or the database. The purpose is signed too, so a
  link for one use (a reset) cannot serve another (an invitation). Verification recomputes the
  signature in constant time and then checks the row (unused, unexpired, not revoked); "unused" is
  enforced by the database, not by the signature. `SECRET_KEY` (at least 32 characters, one per
  environment, set as a Railway variable and never in git) is required at startup, and changing
  it invalidates every outstanding link, which is the emergency switch if it ever leaks. Login and reset responses must not reveal whether an email is registered.

## Authorization

- Model: Role-based, combined with two kinds of data scope: tenant (a staff user can only ever
  touch rows with their own `company_id`) and assignment (recruiters via `JobRecruiter`,
  interviewers via `InterviewParticipant`). Candidates are scoped to rows they own.
- Enforcement pattern:
  - Every route declares its permission through a single FastAPI dependency (working name
    `require_permission(...)` in `backend/app/auth/permissions.py`). A route without one is a
    bug, and a CI test fails the build if any registered route lacks a permission declaration.
  - Data access goes through functions that take the current user and always apply the tenant and
    assignment filter (`backend/app/services/`); route handlers never build unscoped queries.
  - A "not found" response is returned for rows outside the caller's scope, rather than "forbidden",
    so ids cannot be probed across tenants.
  - Blind scoring is enforced in the scorecard query (return only the caller's own scorecard until
    they have submitted theirs), not in the UI.
- Automated tests gate every pull request (all in `backend/tests/`, run by the `backend` job):
  - Route gate (`test_route_gate.py`): every route declares `require_permission` or
    `public_route`. The audit follows routers included into the app (FastAPI does not flatten
    them) and refuses, rather than skips, anything it cannot read: an `include_router` with a
    prefix or extra dependencies, or an unrecognised kind of route.
  - Role x endpoint matrix (`test_route_matrix.py`): generated from the route table and compared
    with a hand-written `POLICY`; every role is called against every route live. A new route, or
    a changed permission, fails until `POLICY` is updated in the same pull request.
  - Tenant isolation (`test_tenant_isolation.py`): every route must be classified. Id-based routes
    are attacked as company A against company B's ids and must answer 404 (each attack has a
    control that must succeed on A's own data); lists must contain only the caller's rows; B's
    data must be untouched afterwards. Routes that are public by design are classified too, with
    a reason, and a route with an id in its path may be exempted from the attack only if it is
    public (`PUBLIC_ROUTES_WITH_ID`, which a test checks); their own tests
    (`test_public_jobs.py`) prove that nothing but open jobs and the whitelisted fields leaves.

## Data Protection

- Encryption at rest: Whatever the hosting platform provides for the database volume and the
  storage bucket (verify on Railway, [TODO]). Google refresh tokens are additionally encrypted at
  the application level (key via environment variable; scheme [TODO]).
- Transit security beyond the HTTPS baseline in CLAUDE.md: [TODO — confirm that app-to-database
  traffic is private/TLS on Railway]
- Fields requiring extra protection: `password_hash`, session tokens (`Session`) stored only as hashes; invitation and
  `UserToken` links are signed with `SECRET_KEY` and not stored (see Authentication); `GoogleCalendarConnection.refresh_token_encrypted`;
  candidate PII and `Note`/`Scorecard` content never written to logs.

## File Upload Handling

> **Skip unless** this app accepts file uploads — imports, attachments, avatars, anything.

Applies: candidates upload resumes. Two rules are not decisions and apply regardless of what's
below (see CLAUDE.md > Security Baseline): the stored path is generated by the app rather than
taken from the uploaded filename, and the authorization check passes before the file is written,
not after.

The per-project choices:

- Allowed file types and max size: PDF and DOCX, maximum 5 MB. The type is verified from the file
  contents (magic bytes), not only the extension or the client-sent content type.
- Storage location and naming convention: Railway storage bucket (S3-compatible); a small
  S3-compatible server (Versity S3 Gateway) stands in for it locally and in CI. The stored key is generated by the app (a random
  id, never derived from the original filename).
- Whether the DB stores a full path or just a filename resolved against a configured base
  directory: Only the generated `storage_key` is stored (`File.storage_key`); the bucket and
  endpoint come from configuration.
- Whether the original filename is retained as display metadata, and where: Yes, in
  `File.original_filename`, display-only, and escaped on output.
- Downloads: resumes are served through an authorized endpoint (or short-lived signed URL) that
  checks the caller may see that application/candidate. The bucket itself is private. Which of the
  two: [TODO]
- Malware scanning of uploads: [TODO]

## Threat Model (lightweight)

- Biggest realistic threat to this app: Cross-tenant data exposure — one company (or a candidate)
  reading another's applications, notes or resumes through a missing `company_id` filter or a
  guessable id. Second: leaking evaluations that must stay hidden (blind scores, internal notes,
  rejection comments) to the wrong role. Third: account takeover through account-linking or
  invitation/reset token flaws.
- Anything explicitly out of scope for launch (accepted risk, revisit later): MFA, formal GDPR
  certification, malware scanning of resumes [TODO], advanced bot protection. Known and accepted
  until the phase that fixes them:
  - Company signup is open and not rate limited, so someone could create many companies (Phase 2).
  - Candidate registration (`POST /api/candidates`) is open and not rate limited, like company
    signup, so someone could create many candidate accounts (Phase 5).
  - The public job routes (`/api/public/jobs`) need no login and are not rate limited. They are
    bounded instead: keywords and location are at most 200 characters, a page holds at most 100
    rows, the page number is capped, and the query is a single indexed lookup. Only open jobs
    and a fixed list of fields are returned (Phase 4).
  - A failed signup still hints that an email is registered. Making it fully non-revealing would
    mean emailing the existing owner instead, which v1 does not do (login and password reset do
    not reveal it).
  - "Forgot password" answers identically for every address, but the request does slightly more
    database work for an existing account (it creates a link and queues an email). The email itself
    is sent by the worker, not in the request, so no mail-server delay shows; the remaining
    difference is a couple of inserts, too small to measure reliably over a network.
  - The route audit reads FastAPI internals; a FastAPI upgrade that changes them fails the test
    loudly rather than passing silently, so check it first when upgrading.
  Others: [TODO]

## Audit / Logging

- What actions must be logged for audit purposes: See `data-model.md` > Change Auditing —
  application stage changes, rejections, withdrawals, scorecard submissions, notes, job status
  changes, interview create/reschedule/cancel, role changes and deactivations, assignment
  changes.
- Log retention: [TODO]
- If this app does bulk operations — what's logged per record: Not applicable in v1 (no bulk
  operations).

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
  additional method (Phase 8). Password hashing: bcrypt or argon2 per `CLAUDE.md`; library
  [TODO — needs approval]. Password rules: minimum 12 characters, no composition rules (length
  over symbols). Login is rate-limited per account and per IP; limits and lockout behavior are
  chosen in Phase 2's plan: [TODO]
- Session handling: Server-side sessions stored in the `Session` table, referenced by an opaque
  random token in an httpOnly, Secure, SameSite cookie. The SPA is served from the same origin as
  the API, so there is no CORS and no token in JavaScript. State-changing requests require a CSRF
  header: the session cookie is SameSite=Lax, and every state-changing request must carry a custom
  header the SPA sets (exact token scheme chosen in Phase 2's plan: [TODO]). Idle timeout: 30 minutes for staff roles, 7 days for candidates.
  Absolute lifetime: [TODO]. Sessions are revoked on deactivation, password change and account
  deletion.
- MFA required: No (non-goal for v1).
- If the identity comes from an external provider (Google): an unknown Google email creates a
  candidate account, never a staff account. An existing account is linked only if Google reports
  the email as verified and the existing account's email is verified too; otherwise refuse and
  ask the user to log in with the password first. A deactivated or anonymized user cannot sign in
  by any method. Whether staff may use Google at all: [TODO]
- Invitations and email-verification/reset tokens: random, single-use, stored hashed, expiring
  (invitation 7 days, email verification 24 hours, password reset 1 hour). Login and reset responses must not reveal whether an email is registered.

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
- Two automated tests gate every pull request:
  - Tenant isolation: two companies are created, and every company-scoped endpoint is called as a
    user of company A against company B's ids. All must be denied.
  - Role x endpoint matrix, generated from the route table, asserting each role gets the expected
    allow/deny on each route.

## Data Protection

- Encryption at rest: Whatever the hosting platform provides for the database volume and the
  storage bucket (verify on Railway, [TODO]). Google refresh tokens are additionally encrypted at
  the application level (key via environment variable; scheme [TODO]).
- Transit security beyond the HTTPS baseline in CLAUDE.md: [TODO — confirm that app-to-database
  traffic is private/TLS on Railway]
- Fields requiring extra protection: `password_hash`, tokens (`Session`, `Invitation`,
  `UserToken`) stored only as hashes; `GoogleCalendarConnection.refresh_token_encrypted`;
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
- Storage location and naming convention: Railway storage bucket (S3-compatible); a MinIO
  container stands in for it locally and in CI. The stored key is generated by the app (a random
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
  certification, malware scanning of resumes [TODO], advanced bot protection. Others: [TODO]

## Audit / Logging

- What actions must be logged for audit purposes: See `data-model.md` > Change Auditing —
  application stage changes, rejections, withdrawals, scorecard submissions, notes, job status
  changes, interview create/reschedule/cancel, role changes and deactivations, assignment
  changes.
- Log retention: [TODO]
- If this app does bulk operations — what's logged per record: Not applicable in v1 (no bulk
  operations).

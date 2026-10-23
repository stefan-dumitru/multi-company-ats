# Functional Specification

## Product Overview

- What is this app, in 2-3 sentences: A multi-company applicant tracking system (ATS). Companies
  (tenants) publish jobs, receive applications, move candidates through a fixed hiring pipeline,
  run interviews with blind scoring, and keep an audit trail of every hiring decision. Candidates
  have one global account and apply to jobs at any company, tracking each application's status.
- Who is it for: Small and mid-size companies without dedicated HR software, and the job seekers
  applying to them. It is also a portfolio project: the CI/CD pipeline is a deliverable, not an
  afterthought (see `operations.md` > Environments & Configuration and `SPECS.md` > Build Phases).
- Core problem it solves / why it needs to exist: Hiring teams track applications in spreadsheets
  and email, interviewers see each other's opinions before forming their own, and nobody can say
  afterwards who decided what. Candidates apply blind and never learn where they stand.
- Explicit scope boundary — what's deliberately excluded: Platform super-admin, subscription
  plans, billing, account suspension; hiring-manager role; configurable pipeline templates;
  offer-approval workflow and offer letters ("Offer" is a stage, not a document); custom email
  templates; video-call links; resume parsing / AI matching; MFA; public company career pages.
  (The authoritative list is `first-prompt.md` > Non-goals.)

## Authentication & Identity Source

How it's implemented, and what happens when it fails, is in `security.md` > Authentication.

- Does this app handle its own login, or does it receive an already-authenticated identity from
  an external system? The app handles its own login (email + password, with email verification).
  Google login is an additional method in v1 (Phase 8), not an SSO replacement. No external
  system authenticates users on the app's behalf.
- Who may use Google login: candidates. Whether company staff may also use it: [TODO]
- Google Calendar is a separate connection from Google login: a company user connects their
  Google account to let the app create interview events (see "Schedule an interview").
- Company users join by invitation from a company admin. Candidates self-register. A new company
  is created by self-service signup, and the person who signs up becomes its first company admin.

## User Roles

Four roles. Each user account has exactly one role. Staff roles belong to exactly one company;
candidates belong to no company.

| Role | Description | Data scope | Can do | Cannot do |
|---|---|---|---|---|
| Company admin | Runs a company's account | Everything in their own company | Invite, deactivate and reassign users; assign roles; manage departments; see all jobs, applications, interviews and scorecards in the company; assign recruiters to any job; view company-wide analytics | See any other company's data; see platform-wide data |
| Recruiter | Main day-to-day user | Jobs they are assigned to (via `JobRecruiter`) and those jobs' applications, plus the talent pool of discoverable candidates | Create and edit jobs (creator is auto-assigned); add other recruiters to their jobs; move applications between stages; reject with a reason; add notes; schedule interviews and assign interviewers; see all scorecards for their applications; connect Google Calendar; search the talent pool | Manage users or departments; see jobs they are not assigned to |
| Interviewer | Colleague asked to evaluate candidates | Only interviews assigned to them (via `InterviewParticipant`) | See the candidate's profile and resume for those interviews; submit a scorecard; see other interviewers' scorecards for that interview only after submitting their own | See applications, notes or jobs outside their interviews; move stages; see others' scorecards before submitting |
| Candidate | Job seeker with one global account | Only their own profile and applications, across all companies | Edit profile and resume; opt in/out of the talent pool; browse open jobs; apply; withdraw (and reactivate a withdrawn) application; delete their account | See anything about other candidates; see internal notes, scorecards, or rejection comments |

Landing views with aggregate stats (scoped to the user's data):

- Company admin: company-wide analytics dashboard (see "Search & Reporting").
- Recruiter: analytics dashboard limited to their assigned jobs, plus a "needs action" list
  (new applications, interviews awaiting a decision).
- Interviewer: list of their upcoming interviews and ones awaiting their scorecard. No aggregates.
- Candidate: list of their applications with current status. No aggregates.

Both the dashboards and the lists need a summary endpoint, not just a list endpoint.

## Notifications

> **Skip unless** this app sends messages to someone outside its own logged-in users — email,
> SMS, webhooks, or notifications to a partner organization.

(Skipped: every email recipient is a logged-in user of this app — candidates and staff. The
emails themselves are specified in the use cases below and run through the background worker, see
`operations.md` > Background Jobs & Queues.)

## Search & Reporting

- What's searchable, on which entities, and by which fields?
  - Jobs (candidate-facing): open jobs by keyword over title and description, plus filters for
    location and company.
  - Applications (recruiter/admin): filter by job, stage and status; match candidate name or
    email by prefix. Scoped to the jobs the user can see.
  - Talent pool (recruiter): discoverable candidates only. Fields searchable: [TODO]
- Exact match, prefix, or fuzzy/full-text? Postgres full-text search (`tsvector` column + GIN
  index) for job text. Exact filters and prefix match for applications. Talent pool matching
  method: [TODO]
- What reports or exports does each role need, in what format?
  - Company admin and recruiter: on-screen analytics dashboard only. No CSV/PDF export in v1.
  - Candidate: a data export of their own data (supports GDPR awareness, see `security.md`):
    format and delivery [TODO].
- Do any reports need aggregated or denormalized data that the transactional model won't answer
  efficiently? The dashboard needs only counts by stage, counts over time and counts by rejection
  reason. These are answered from `Application` and `ApplicationStageHistory` with indexes; no
  separate reporting table in v1.

Dashboard contents (all scoped to the user's company, and for recruiters to assigned jobs):

- Pipeline funnel: number of applications currently in each stage, per job and overall.
- Open jobs and application volume: count of open jobs, new applications per week.
- Rejection reasons: breakdown of rejections by reason (fixed list, see `data-model.md`).

## Use Cases

The roles table above says *what* each role can do. This section says *how*.

### Company signup and onboarding

- **Role(s):** Future company admin (not yet a user).
- **Trigger:** "Register your company" page.
- **Main flow:** Visitor enters company name, their name, email, password. The app creates the
  `Company` and a `User` with role company admin in one transaction, sends a verification email,
  and logs them in with limited access until the email is verified.
- **Rules & edge cases:** Email already registered -> generic error that does not reveal whether
  the account exists [TODO: exact wording]. Company name need not be unique. The transaction is
  all-or-nothing: no company without an admin. What an unverified admin can do before
  verification: [TODO].

### Invite and deactivate staff

- **Role(s):** Company admin.
- **Trigger:** Users page.
- **Main flow:** Admin enters email and role (recruiter or interviewer, or another admin). The app
  creates an `Invitation` and emails a single-use link. The invitee sets a password and joins the
  company with that role.
- **Rules & edge cases:** An email that already has an account (including a candidate account) is
  rejected: one email is one account. Invitations expire after 7 days. Re-sending invalidates the old
  link. Deactivating a user blocks login and revokes their sessions but keeps all their data;
  their jobs and pending interviews are flagged "needs reassignment" for the admin. An admin
  cannot deactivate the last active admin of a company. Changing a user's role while they have
  pending work: [TODO].

### Candidate applies to a job

- **Role(s):** Candidate.
- **Trigger:** "Apply" on an open job page.
- **Main flow:** Candidate must have a verified account, a complete profile and a resume. Applying
  creates an `Application` in stage Applied, snapshots the candidate's current resume onto it,
  writes a stage-history row and an audit entry, and queues two emails (confirmation to the
  candidate; new-application notice to the job's recruiters: [TODO whether this is in v1]).
- **Rules & edge cases:** One application per candidate per job, enforced by a unique constraint,
  including after withdrawal or rejection (a double-click or retry returns the existing
  application, not an error). Job not open (closed/draft) -> rejected. Job closed between page load
  and submit -> clear message, no application created. Resume missing -> prompt to upload first.
  Required profile fields: [TODO].

### Move an application through the pipeline

- **Role(s):** Recruiter (assigned to the job).
- **Trigger:** Pipeline board or application detail.
- **Main flow:** Recruiter moves an application Applied -> Screening -> Interview -> Offer ->
  Hired. Each move, in one transaction, updates the stage, writes an `ApplicationStageHistory`
  row and an `AuditLog` entry, and queues the candidate email.
- **Rules & edge cases:**
  - Allowed transitions: forward one stage at a time; Rejected from any stage. Skipping stages
    and moving backwards are not allowed.
  - Rejection requires a reason from the fixed list (see `data-model.md`) and takes an optional
    internal comment. The comment is never shown to the candidate. Whether the candidate's
    rejection email includes the reason category: [TODO].
  - Rejection reasons (fixed list): skills/experience mismatch; position filled / better
    candidate selected; candidate withdrew interest or unresponsive; failed interview/assessment;
    other (requires the comment).
  - Concurrent moves use optimistic locking on `Application.version`; the second writer gets a
    "this application changed, reload" error and nothing is overwritten.
  - Hired, Rejected and Withdrawn are terminal for recruiters. Reopening a rejected application:
    [TODO].
  - Closing a job does not touch its in-flight applications; they continue to a decision.

### Schedule an interview

- **Role(s):** Recruiter.
- **Trigger:** Application detail, once it is in the Interview stage.
- **Main flow:** Recruiter creates an `Interview` (round name, date/time, duration, location text)
  and assigns one or more interviewers from active staff of the same company. An application can
  have several interviews (rounds). The app emails the interviewers and the candidate. If the
  recruiter has connected Google Calendar, a background job creates a calendar event with the
  interviewers as attendees.
- **Rules & edge cases:** Calendar failure must not block scheduling: the interview exists and
  emails go out; the event creation is retried by the worker and, after the final failure,
  recorded as failed (see `operations.md`). Recruiter has not connected Google -> the interview
  is created and emailed without an event. Rescheduling or cancelling an interview, and what
  happens to the calendar event: [TODO]. An interviewer who is deactivated after assignment keeps
  the assignment but is flagged for reassignment. Interviewers must belong to the same company.
  Interview times are stored in UTC; display time zone: [TODO].

### Submit a scorecard (blind scoring)

- **Role(s):** Interviewer.
- **Trigger:** "Awaiting your scorecard" list or the interview page.
- **Main flow:** Interviewer sees the candidate's profile and resume, then submits one scorecard
  per interview: overall rating, per-criterion ratings from the fixed criteria set, written
  feedback and a recommendation. Ratings are 1-5. The fixed criteria are technical/role skills,
  communication, problem solving, and culture/team fit. The recommendation is one of strong no,
  no, yes, strong yes. After submitting, they can see the other interviewers' scorecards for that same
  interview.
- **Rules & edge cases:** One scorecard per interviewer per interview (unique constraint; a
  double-submit does not create a second one). Others' scorecards are hidden by the API, not just
  the UI: the endpoint returns only the caller's own scorecard until they have submitted. A
  submitted scorecard is final: no editing. Recruiters and company admins can see each
  scorecard for applications they can access as soon as it is submitted (they do not wait for all
  interviewers). Interviewers cannot see notes or other interviews' scorecards.

### Candidate withdraws, reactivates or deletes their account

- **Role(s):** Candidate.
- **Trigger:** Applications list, account settings.
- **Main flow:** Withdrawing sets the application to Withdrawn and records history. A withdrawn
  application can be reactivated by the candidate; since only one application per job is allowed,
  this is the only way back, and it returns to the stage the application was in before withdrawal.
  Deleting the account anonymizes personal data (name, email, phone,
  resume files, profile fields) while keeping applications, stage history and the audit log, which
  then show "Deleted candidate".
- **Rules & edge cases:** Candidates cannot reactivate a rejected application. Deletion revokes all sessions, frees the email address
  [TODO whether it can be re-registered], and removes the resume file from object storage.
  Anonymization is irreversible. Active applications at deletion time are set to Withdrawn first.

### Opt in to the talent pool and search it

- **Role(s):** Candidate (opt-in), Recruiter (search).
- **Trigger:** Candidate profile setting "visible to employers"; recruiter's talent pool page.
- **Main flow:** A candidate switches on discoverability. Recruiters in any company can then find
  that candidate in the talent pool, within the search fields [TODO].
- **Rules & edge cases:** Only candidates with the flag on and not anonymized are returned.
  Turning the flag off removes the profile from search immediately, but does not affect
  applications that already exist. What a recruiter sees in a talent pool result (full contact
  details, or a limited profile) and what they can do with it (invite to apply, attach to a job):
  [TODO]. Every talent pool profile view is audit-logged [TODO whether in scope].

### Sign in with Google and link accounts

- **Role(s):** Candidate (staff: [TODO]).
- **Trigger:** "Continue with Google" button.
- **Main flow:** Standard OAuth sign-in. If no account has that email, a candidate account is
  created, already verified.
- **Rules & edge cases:** If an account with the same email exists, the Google identity is linked
  only if Google reports the email as verified **and** the existing account's email is verified.
  Otherwise the sign-in is refused with a message to log in with the password first. Google login
  never grants a role other than candidate on its own.

---

If a use case is complex enough that describing it here would take more than a few lines (many
edge cases, a multi-step business process, strict field-by-field rules), give it its own file
instead: `specifications/features/<feature-name>.md`, covering the exact rules, the data it
touches, and its error handling — see `SPECS.md` > Optional Extensions.

> **Skip unless** a use case runs in more than one mode — an import that can be "full replace,"
> "add only," or "remove only," for instance.

(Skipped: no use case runs in more than one mode, and v1 has no file import.)

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
- **Rules & edge cases:** Email already registered -> one generic error ("We couldn't create this
  account. If you already have one, log in instead."). It does not state that the account exists,
  but the failure itself still hints at it; a fully non-revealing flow needs an email to the
  existing owner, which v1 does not send. Company name need not be unique. The transaction is all-or-nothing:
  no company without an admin. Until the address is verified the admin can log in and use their own account (see who
  they are, log out, ask for a new link) and nothing else: every other call is refused with
  `403 {"detail": "Verify your email first.", "code": "email_not_verified"}`, and the app shows a
  "verify your email" screen with a Resend button. The verification link is signed, single-use and
  expires after 24 hours; asking for a new one voids the old one, at most 3 per hour. Invited staff
  verify their address too (accepting a link an admin passed on proves nothing about the inbox).
  The same rule applies to every account, whichever way it was created.

### Reset a forgotten password

- **Role(s):** Any user with a password (company staff and candidates). Not logged in.
- **Trigger:** "Forgot your password?" on the login page.
- **Main flow:** The user enters their email. Whatever the address is, the app answers the same
  words ("If an account exists for that address, we have sent a link to reset the password"). If an
  active account has that address, a reset email is queued in the same transaction. The email
  holds a signed, single-use link that expires after 1 hour. Opening it shows a "choose a new
  password" page; the user submits a password that meets the rules (12 to 128 characters). The
  password is replaced, the user is logged out everywhere (every session ends), and they are told
  by email that their password was changed. They then log in with the new password; the link
  itself never logs anyone in.
- **Rules & edge cases:** The answer must never reveal whether an address has an account, and
  neither may a limit: at most 3 reset links per hour per account, and beyond that nothing more is
  sent while the answer stays identical. Asking again voids the older link. A weak password is
  refused without using up the link. A used, expired, forged or wrong-purpose link, and a link
  for a deactivated account, all get the same generic refusal. Using the link also clears the
  login lockout and counts as proof of the inbox (an unverified address becomes verified). The
  reset is written to the audit log (who and when, never the password or the link). Deactivated
  accounts cannot reset.

### Invite and deactivate staff

- **Role(s):** Company admin.
- **Trigger:** Users page.
- **Main flow:** Admin enters email and role (recruiter or interviewer, or another admin). The app
  creates an `Invitation` and queues an email with a single-use link (the worker sends it; the
  admin is also shown the link once, at creation, in case the email goes astray). The invitee sets a name and password and joins
  the company with that role; the role and company come from the invitation, never from the
  invitee.
- **Rules & edge cases:** An email that already has an account (including a candidate account) is
  rejected: one email is one account. Invitations expire after 7 days. Re-sending invalidates the old
  link; an email still waiting in the queue for a link that has since been replaced, accepted or
  expired is not sent. Deactivating a user blocks login and revokes their sessions but keeps all their data;
  their jobs and pending interviews are flagged "needs reassignment" for the admin. An admin
  cannot deactivate or demote the last active admin of a company (checked under a lock, so two
  admins acting at the same moment cannot empty the company of admins). An admin can reactivate a
  deactivated user: they log in again with their old password, but sessions revoked at
  deactivation stay revoked. Repeating an action that is already in effect changes nothing and
  writes no audit row. Changing a user's role while they have
  pending work: [TODO].

### Manage departments

- **Role(s):** Company admin writes; admins and recruiters read (a recruiter needs the list to
  pick a department for a job).
- **Trigger:** Departments page.
- **Main flow:** The admin adds a department, renames it, archives it or brings it back, or deletes
  it. Every change is written to the audit log.
- **Rules & edge cases:** A name is 1 to 100 characters, trimmed, and unique within a company
  ignoring case ("Sales" and "sales" clash; two admins adding the same name at once cannot both
  succeed). Another company's department is "not found". An archived department stays on the jobs
  that use it but cannot be chosen for a new job or a change of department. A department can be
  deleted only while no job, of any status, has ever used it; otherwise it is archived instead.
  Repeating an archive, or renaming to the same name, changes nothing and writes no audit row.

### Create, publish and close a job

- **Role(s):** Company admin (any job of the company); recruiter (jobs assigned to them).
- **Trigger:** "New job" on the Jobs page; the job's own page.
- **Main flow:** Title, location, department and description are entered; the job starts as a
  draft. A recruiter who creates it is assigned to it; an admin who creates it is not (an admin is
  not a recruiter) and adds recruiters afterwards. The job is edited while it is a draft or open,
  then published (open) and later closed. A draft can be deleted instead. Recruiters on a job are
  added by an admin or by a recruiter already on it, and removed the same way.
- **Rules & edge cases:** The list shows an admin every job of the company and a recruiter only the
  jobs assigned to them; any other job is "not found". Publishing needs at least one active
  recruiter on the job, and an open job cannot lose its last active recruiter (409). Closed is
  final: a closed job cannot be edited or reopened, and a draft cannot be closed. Only a draft can
  be deleted (once applications exist, only a draft without applications). Repeating a status
  change that is already in effect (a double click) succeeds and changes nothing. Every edit,
  publish and close quotes the job's version; if someone else changed the job meanwhile the change
  is refused (409) and the screen offers to load the latest version, keeping what was typed. Two
  people acting at the same moment take turns (the job row is locked). A job whose recruiters have
  all been deactivated is flagged "needs a recruiter". Create, edit, publish, close, delete and
  recruiter changes are audited, in the same transaction; the audit row names the fields that
  changed, never the text.

### Search and read open jobs

- **Role(s):** Anyone, logged in or not.
- **Trigger:** "Find jobs" in the menu, or the home page.
- **Main flow:** The visitor enters keywords and/or a location and presses Search; results are
  open jobs of every company, best match first (newest first without keywords), 20 per page. A
  card links to the job's page, which shows the full description and a link to the company's other
  jobs. What was asked for lives in the address, so a search can be shared as a link.
- **Rules & edge cases:** Only open jobs are ever reachable: drafts and closed jobs are missing
  from the list and from search, and answer "not found" by id, so a link to a job that closed shows
  "no longer available". Keywords use Postgres full-text search in English: other forms of a word
  match, a title match outranks a description match, and quoted phrases, `or` and a leading `-`
  work; odd input never fails. Keywords and location are at most 200 characters; a `%` or `_` in
  the location is a plain character. Only a fixed set of fields is shown (never who works on the
  job). Candidates cannot apply yet (Phase 5).

### Register as a candidate and keep a profile

- **Role(s):** Anyone (registers); Candidate (profile).
- **Trigger:** "Register" as a job seeker; the Profile page.
- **Main flow:** The visitor enters their name, email and a password. The app creates a candidate
  account (no company) and its profile in one transaction, queues the verification email, and logs
  them in with limited access, exactly like company signup. Until the email is verified the candidate
  can see who they are, log out and ask for a new link, and nothing else. A verified candidate reads
  and changes their own profile: name, phone, location and resume.
- **Rules & edge cases:** The same words are used whether or not the email is already taken (a
  company staff address counts too: one email is one account), a weak password (under 12
  characters) is refused, and the request cannot choose a role or a company. Phone is up to 30
  characters of digits, spaces and `+ ( ) - .`; location is up to 200 characters; sending null or
  blanks clears either; leaving a field out leaves it alone. The email address cannot be changed
  here. The resume is a PDF or a Word (.docx) file of at most 5 MB; its type is read from the file
  itself, a new upload replaces the old one (an old file that no application uses is removed in
  the background), at most 5 uploads are allowed per hour, and when storage is down the upload
  fails with a clear message and nothing changes. A candidate can only ever reach their own
  profile and resume: no route takes a candidate id. Candidate
  sessions last 7 days idle and 30 days in all (staff: 30 minutes and 12 hours).

### Candidate applies to a job

- **Role(s):** Candidate.
- **Trigger:** "Apply" on an open job page.
- **Main flow:** Candidate must have a verified email and a resume on file; nothing else in the
  profile is required (phone and location are optional). Applying creates an `Application` in
  stage Applied, copies the job's company onto it, snapshots the candidate's current resume onto
  it, writes a stage-history row and an audit entry (filed under the job's company), and queues
  one email, the confirmation to the candidate. All of this is one transaction. Recruiters get no
  email in v1: they see new applications on the job's page.
- **Rules & edge cases:** One application per candidate per job, enforced by a unique constraint,
  including after withdrawal or rejection: applying again returns the existing application (200,
  not an error) and changes nothing, even if the resume has since gone or the job has since
  closed. Two simultaneous applications make one (the loser finds the winner's). A closed job ->
  409 `job_not_open` with a clear message and nothing created; a draft or unknown job -> "not
  found", exactly like a job that does not exist. No resume on file (or one removed from
  storage) -> 409 `resume_required`. A later replacement of the resume does not change the
  snapshot on an existing application. A candidate sees the job, the company and the stage of their
  own applications, newest first, and nothing a recruiter wrote.
  Staff (an admin for any job of the company, a recruiter for jobs assigned to them) see who applied
  to a job: name, email, stage and date, newest first, withdrawn ones included and marked. They can
  download the resume the candidate applied with (the snapshot, not a newer upload). Any job or
  application outside their reach is "not found". Interviewers see none of this.
  **On screen:** the public job page offers Apply to a verified candidate who has a resume (and
  shows "You applied on <date>" afterwards, or that they withdrew); a visitor is asked to log in or
  register and is brought back to the job; a candidate without a verified email or a resume is
  pointed to their profile; staff see no apply controls. "My applications" lists a candidate's own
  applications as cards, with Withdraw (after a confirmation) and Reactivate (disabled, with the
  reason, once the job is closed). The job page learns whether the candidate already applied from
  `GET /api/applications?job_id=<job>`. For staff, the job page has an Applicants section (not on
  a draft): one card per application with name, email, stage, date and a "Download resume" link
  that opens in a new tab; it loads on its own, so a failure there does not break the rest of the
  page.

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
    internal comment (at most 2000 characters; required for `other`). Neither is ever shown to the
    candidate, and the candidate's rejection email is a kind, generic message that names no
    reason.
  - Rejection reasons (fixed list): skills/experience mismatch; position filled / better
    candidate selected; candidate withdrew interest or unresponsive; failed interview/assessment;
    other (requires the comment).
  - Concurrent moves use optimistic locking on `Application.version`; the second writer gets a
    "this application changed, reload" error and nothing is overwritten.
  - Hired, Rejected and Withdrawn are terminal for recruiters (409 `application_not_active`).
    A rejected application cannot be reopened in v1; because a candidate has one application per
    job, a mistaken rejection cannot be put right. Known limit.
  - Only recruiters assigned to the job move, reject or write notes. A company admin can read the
    application, its history and its notes but does not decide; interviewers and candidates have no
    access. Anything outside the caller's scope is "not found".
  - A move needs no target: the request carries only the version, and the server moves the
    application to the next stage (Applied -> Screening -> Interview -> Offer -> Hired). The
    candidate gets one email per milestone (Screening, Interview, Offer, Hired) and one on
    rejection, sent by the worker. A candidate withdrawing at the same moment makes the
    recruiter's version stale, so the move is refused with the conflict message.
  - Audit actions written: `application.stage_changed`, `application.rejected` (the new value
    holds the stage and the reason category, never the comment).
  - Notes: assigned recruiters add internal notes to an application (1 to 4000 characters, trimmed,
    append-only: no edit, no delete); company admins can read them; interviewers and candidates
    can neither read nor write them and no response a candidate can reach contains one. Each note
    adds a `note.added` audit row that names the application and never holds the text.
  - On screen: a staff page per application (`/manage/applications/<id>`, reached from a name in the
    job's Applicants list) shows the candidate's details and resume, a progress line, any rejection
    with its internal reason and comment, and the history. Assigned recruiters get one "Move to
    <next stage>" button and a Reject dialog (reason list, comment required for `other`); company
    admins see the page read-only. If someone else changed the application first, the page shows the
    conflict message with a Reload button and changes nothing. The same page has a Notes section:
    the notes newest first (author, date, text with its line breaks, paged), and for recruiters a
    box to add one (blank notes cannot be sent, 4000 characters at most); it loads on its own, so a
    failure there does not break the rest of the page.
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
  is created and emailed without an event. A recruiter can cancel or reschedule an interview, and
  the calendar event is deleted or updated to match (decided for v1; the calendar part comes with
  the Google step). An interviewer who is deactivated after assignment keeps the assignment
  but is flagged for reassignment ("needs reassignment"). Interviewers must be active users with
  the Interviewer role in the same company; anything else is refused with one answer
  (`invalid_interviewer`), so it cannot be used to find out who exists elsewhere.
  Interview times are stored in UTC and sent with their zone (a time without one is refused);
  screens show each person's browser time zone, and emails state the time in UTC and say so.
  Scheduling rules (built): only the job's assigned recruiters schedule or cancel (admins can read
  the interviews of an application, nobody else can); the application must be in the Interview
  stage (409 `application_not_in_interview`) and the time in the future (409
  `interview_in_the_past`); round name up to 100 characters, location up to 300, duration 5 to 480
  minutes, 1 to 10 interviewers. Scheduling locks the application, so it cannot race a rejection.
  Cancelling needs the interview's version (a stale one is the usual conflict) and only a
  scheduled interview can be cancelled (409 `interview_not_scheduled`). Each change writes an
  `interview.scheduled` or `interview.cancelled` audit row (ids and status only) and queues one
  email per interviewer and one to the candidate, in the same transaction. The candidate is told
  when and where, never who the interviewers are.
  Changing an interview (built): `PATCH` with the version and only the fields to change (round
  name, time, duration, location, the list of interviewers). The new time must be in the future
  and only a scheduled interview can be changed. Sending what it already has changes nothing: no
  new version, no audit row, no email. People already assigned may stay even if they were
  deactivated since; anyone added must be an active interviewer of the company. If the time,
  place or round changed, everyone who stays and the candidate get a "rescheduled" email; a
  newly added interviewer gets the "scheduled" email; a removed one gets a "no longer
  assigned" email. A deactivated interviewer is never emailed. The audit row
  (`interview.updated`) names which parts changed and never their values. (Removing an
  interviewer who has already submitted a scorecard is refused once scorecards exist.)
  When an application is rejected or withdrawn, its scheduled interviews are cancelled in the
  same transaction (audited as `interview.cancelled` by whoever caused it, emails to the
  interviewers only: the candidate either did it or already got the rejection). Interviews that
  are completed or already cancelled are left as they are, and reactivating a withdrawn
  application does not bring cancelled interviews back: schedule them again.
  On screen: the application page has an Interviews section (not shown when the application is
  past the Interview stage and nothing was held). Each interview shows its round, the time in the
  viewer's own time zone (named), duration, location, interviewers (a deactivated one marked, with a
  "needs a new interviewer" notice) and status, and the scorecards submitted so far, each with its
  ratings, recommendation and feedback. Assigned recruiters get "Schedule an interview" (Interview
  stage only; round name, date and time in their own zone, duration, location, interviewers picked
  from `GET /api/interviewers`, which lists the company's active interviewers for recruiters),
  "Reschedule" (sends only what changed and the version) and "Cancel interview" (after a
  confirmation). Company admins read the same section and change nothing. A stale change shows the
  conflict message with a Reload button. The section loads on its own, and asks again whenever the
  application changes, so rejecting an application shows its interviews as cancelled.

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
  Built (Phase 7): an interviewer has `GET /api/my/interviews` (paged; `filter=upcoming` for
  scheduled ones still to come, `filter=awaiting` for scheduled ones that have started and have
  no scorecard of theirs), `GET /api/my/interviews/{id}` (the interview, the candidate's name,
  email, phone and location, their own scorecard, and `others_visible` plus the colleagues'
  scorecards only once they have submitted theirs), `GET /api/my/interviews/{id}/resume` (the
  resume the candidate applied with) and `POST /api/my/interviews/{id}/scorecard`. Any
  interview they are not assigned to is "not found". Once an interview is cancelled the
  candidate is no longer shown to the interviewers and the resume is not served (the person
  may have been rejected or withdrawn); scorecards already submitted stay readable. Blind
  scoring is decided in the query: colleagues' scorecards are not even fetched until the
  caller has submitted, and the detail never reveals who has or has not scored. A scorecard
  has five 1-5 ratings (overall, technical, communication, problem solving, culture), feedback
  (1 to 4000 characters, trimmed) and a recommendation; a second submit is refused with 409
  `scorecard_already_submitted` and changes nothing; a cancelled interview takes none. When
  every active interviewer has submitted the interview becomes `completed` (a deactivated
  interviewer does not hold it open). Recruiters and admins read each scorecard as soon as it is
  submitted through `GET /api/interviews/{id}/scorecards`, within their usual scope. An
  interviewer who has submitted cannot be removed from the interview (409
  `interviewer_has_scored`). Audit: `scorecard.submitted` (names the interview, never the
  feedback or ratings) and `interview.completed`.

### Candidate withdraws, reactivates or deletes their account

- **Role(s):** Candidate.
- **Trigger:** Applications list, account settings.
- **Main flow:** Withdrawing sets the application to Withdrawn and records history. A withdrawn
  application can be reactivated by the candidate; since only one application per job is allowed,
  this is the only way back, and it returns to the stage the application was in before withdrawal.
  Deleting the account anonymizes personal data (name, email, phone,
  resume files, profile fields) while keeping applications, stage history and the audit log, which
  then show "Deleted candidate".
- **Rules & edge cases:** Withdrawing is allowed from Applied, Screening, Interview and Offer (not
  after a hire or a rejection: 409 `application_ended`), remembers the stage, and records history
  and an audit entry; withdrawing again changes nothing. Reactivating puts the application back in
  the remembered stage, and only while the job is still open (409 `job_not_open` otherwise);
  reactivating one that is not withdrawn changes nothing. Both change the application's version and
  take turns with other changes to the same application (the row is locked). Another candidate's
  application is "not found". Candidates cannot reactivate a rejected application. Deletion revokes all sessions, frees the email address
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

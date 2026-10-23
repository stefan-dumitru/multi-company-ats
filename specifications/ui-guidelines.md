# UI / Design Guidelines

Only the cross-feature, durable design decisions go here. Layout of an individual screen belongs
in that feature's Plan Mode session, informed by this file — not spec'd upfront here.

## Design System

- Component library / design system: Tailwind CSS + shadcn/ui (built on Radix primitives). React
  single-page app served from the same origin as the API (see `security.md` > Authentication).
- Brand colors / typography: [TODO]
- Light/dark mode: Both, from the start. Colors are defined as theme tokens (CSS variables) so
  components never hard-code a color; user preference defaults to the OS setting.
- Responsive targets (mobile, tablet, desktop — which are must-support): Candidate-facing pages
  (job search, job detail, apply, profile, application list) must work on mobile and desktop.
  Staff pages (pipeline, dashboards, user management) are desktop-first and must stay usable on
  tablet; mobile staff layout is best-effort.
- Exact breakpoints and the layout change at each, not just which targets are supported: [TODO]
- Component structure convention: [TODO]
- Browser/device support matrix — what's actually supported vs. best-effort: [TODO]

## Information Architecture

- Top-level navigation structure: [TODO — decided per role in the Phase 2 plan]
- How roles (from functional.md) map to what nav/screens they see:
  - Candidate: Jobs (search), My applications, Profile (resume, talent pool opt-in, delete
    account).
  - Recruiter: Dashboard, My jobs, Applications, Interviews, Talent pool, Settings (connect
    Google Calendar).
  - Interviewer: My interviews (including those awaiting a scorecard).
  - Company admin: everything a recruiter sees across the whole company, plus Users and
    Departments.
  - Unauthenticated: job search and job detail pages, login, candidate registration,
    "register your company".
  - The SPA hides navigation a role cannot use, but that is cosmetic: the server decides (see
    `CLAUDE.md` > Security Baseline).

## Key Flows

- Company signup -> verify email -> invite first staff.
- Candidate: find a job -> register/log in -> complete profile and resume -> apply -> track
  status.
- Recruiter pipeline: review new applications -> advance or reject (with reason) -> schedule
  interview -> read scorecards -> offer / hire / reject.
- Interviewer: open assigned interview -> read candidate profile and resume -> submit scorecard
  -> then see other interviewers' scorecards.
- Concurrency conflict (a stale pipeline move) must surface as a clear "reload" message, not a
  silent failure. Exact UX: [TODO]

## Accessibility

- Target conformance level: WCAG 2.1 AA.
- Anything specific (keyboard nav required, screen-reader-tested flows, etc.): [TODO]
- Minimum touch target size and spacing, if touch is a supported input: [TODO]

## Feedback & Error States

Not discussed in the interview; the conventions below are left for the first UI phase to decide
with you.

- Error message convention by category: [TODO]
- Success/confirmation message convention: [TODO]
- Loading-state convention for anything async: [TODO]
- Empty-state convention: [TODO]
- Client vs. server validation: The server is authoritative (see `CLAUDE.md` > Security
  Baseline). How the client mirrors the rules without drifting: [TODO]
- Session-expiry behavior (staff sessions idle out after 30 minutes): what the user sees and
  whether unsaved input survives: [TODO]

## Localization & Formatting

> **Skip unless** this app has more than one language, serves users across time zones, or
> displays money. Retrofitting i18n is expensive, so answer the first question even if the answer
> is "English only, and that won't change."

This section applies: interviews carry a date and time and candidates and companies may be in
different time zones. It was not covered in the interview, so everything is open.

- Languages supported now, and whether more are expected later: [TODO]
- Date, number, and currency formatting convention per locale: [TODO]
- Time zone handling for *display* — timestamps are stored in UTC (see `data-model.md`); which
  zone interview times are shown in (viewer's, interview's, company's): [TODO]
- RTL layout support needed: [TODO]

## Per-Screen Specification Files

For an app with many distinct screens, don't try to capture every screen's layout in this file —
give a genuinely complex screen its own spec instead: `specifications/pages/<page-name>.md`,
covering: overview, which roles see it and what each can do, layout per breakpoint,
features/interactions, which entities from `data-model.md` it reads/writes, API endpoints it
calls, state it manages, error states, and any mobile/accessibility notes specific to that
screen.

Only write one when a screen is complex enough that Plan Mode alone would risk missing something
— not for every screen by default. Doing this for every screen upfront is exactly the
over-specification this template's default workflow (see `SPECS.md`) is trying to avoid.
Likely candidates in this app: the recruiter pipeline board and the analytics dashboard.

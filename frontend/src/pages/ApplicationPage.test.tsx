import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, candidateUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'
import type { ApplicationDetail } from './application/types'

const NEXT: Record<string, string | null> = {
  applied: 'screening',
  screening: 'interview',
  interview: 'offer',
  offer: 'hired',
  hired: null,
  rejected: null,
  withdrawn: null,
}

function detail(overrides: Partial<ApplicationDetail> = {}): ApplicationDetail {
  return {
    id: 'a1',
    job_id: 'j1',
    job_title: 'Backend Engineer',
    candidate_name: 'Cara Candidate',
    candidate_email: 'cara@example.test',
    candidate_phone: '+47 123 45 678',
    candidate_location: 'Oslo',
    stage: 'applied',
    next_stage: 'screening',
    version: 1,
    applied_at: '2026-11-10T09:00:00Z',
    rejection: null,
    history: [
      {
        from_stage: null,
        to_stage: 'applied',
        changed_by_name: 'Cara Candidate',
        changed_at: '2026-11-10T09:00:00Z',
      },
    ],
    ...overrides,
  }
}

function startServer(options: { user?: User; application?: ApplicationDetail | null } = {}) {
  const user = options.user ?? recruiterUser
  const state = {
    application: options.application === undefined ? detail() : options.application,
    failNext: {} as Record<string, Reply>,
    // Someone else changes the application behind the page's back before the next change.
    changeBehindBack: false,
  }

  const backend = stubBackend((call) => {
    const url = new URL(call.path, 'http://app.test')
    const key = `${call.method} ${url.pathname}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(user) }
    if (key === 'GET /api/applications/a1/notes') {
      return { status: 200, body: { items: [], total: 0, page: 1, page_size: 20 } }
    }
    const match = /^\/api\/applications\/([^/]+)(?:\/(advance|reject))?$/.exec(url.pathname)
    if (!match) throw new Error(`Unplanned request in test: ${key}`)
    const application = state.application
    if (!application || application.id !== match[1]) {
      return { status: 404, body: { detail: 'Not found.' } }
    }
    if (call.method === 'GET') return { status: 200, body: application }

    if (state.changeBehindBack) {
      state.changeBehindBack = false
      application.version += 1
      application.stage = 'screening'
      application.next_stage = 'interview'
    }
    const body = call.body as { version: number; reason?: string; comment?: string }
    if (body.version !== application.version) {
      return {
        status: 409,
        body: {
          detail: 'This application was changed by someone else. Reload it and try again.',
          code: 'version_conflict',
        },
      }
    }
    const from = application.stage
    if (match[2] === 'advance') {
      application.stage = application.next_stage as ApplicationDetail['stage']
    } else {
      application.stage = 'rejected'
      application.rejection = {
        from_stage: from as 'applied',
        reason: body.reason as 'other',
        comment: body.comment ?? null,
      }
    }
    application.next_stage = NEXT[application.stage] as ApplicationDetail['next_stage']
    application.version += 1
    application.history.push({
      from_stage: from,
      to_stage: application.stage,
      changed_by_name: user.full_name,
      changed_at: '2026-11-12T10:00:00Z',
    })
    return { status: 200, body: application }
  })

  return { state, calls: backend.calls }
}

async function openApplication() {
  renderApp('/manage/applications/a1')
  await screen.findByRole('heading', { name: 'Cara Candidate' })
}

describe('ApplicationPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows who applied, for which job, and how to reach and read them', async () => {
    startServer()
    await openApplication()

    expect(screen.getByText('cara@example.test')).toBeInTheDocument()
    expect(screen.getByText('+47 123 45 678')).toBeInTheDocument()
    expect(screen.getByText('Oslo')).toBeInTheDocument()
    expect(screen.getByText(`Applied ${formatDate('2026-11-10T09:00:00Z')}`)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /backend engineer/i })).toHaveAttribute(
      'href',
      '/manage/jobs/j1',
    )
    const resume = screen.getByRole('link', { name: /download resume/i })
    expect(resume).toHaveAttribute('href', '/api/applications/a1/resume')
    expect(resume).toHaveAttribute('target', '_blank')
    expect(resume).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('leaves out a phone number or location the candidate did not give', async () => {
    startServer({ application: detail({ candidate_phone: null, candidate_location: null }) })
    await openApplication()

    expect(screen.queryByText(/phone/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/location/i)).not.toBeInTheDocument()
  })

  it('shows names and emails as text, never as markup', async () => {
    startServer({ application: detail({ candidate_name: '<b>Bold</b> Bob' }) })
    renderApp('/manage/applications/a1')

    expect(await screen.findByRole('heading', { name: '<b>Bold</b> Bob' })).toBeInTheDocument()
    expect(document.querySelector('main b')).toBeNull()
  })

  it('marks the current stage on the progress line', async () => {
    startServer({
      application: detail({ stage: 'interview', next_stage: 'offer' }),
    })
    await openApplication()

    const progress = screen.getByRole('list', { name: /progress/i })
    const current = within(progress).getByRole('listitem', { current: 'step' })
    expect(current).toHaveTextContent('Interview')
    expect(within(progress).getAllByRole('listitem')).toHaveLength(5)
  })

  it('shows the history, oldest first, with who changed what', async () => {
    startServer({
      application: detail({
        stage: 'screening',
        next_stage: 'interview',
        version: 2,
        history: [
          {
            from_stage: null,
            to_stage: 'applied',
            changed_by_name: 'Cara Candidate',
            changed_at: '2026-11-10T09:00:00Z',
          },
          {
            from_stage: 'applied',
            to_stage: 'screening',
            changed_by_name: 'Rae Recruiter',
            changed_at: '2026-11-11T09:00:00Z',
          },
        ],
      }),
    })
    await openApplication()

    const history = screen.getByRole('list', { name: /history/i })
    const items = within(history).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Applied')
    expect(items[0]).toHaveTextContent('Cara Candidate')
    expect(items[1]).toHaveTextContent('Applied to Screening')
    expect(items[1]).toHaveTextContent('Rae Recruiter')
  })

  // ---- moving ---------------------------------------------------------------------------------

  it('moves the application forward and shows the new stage and the next step', async () => {
    const server = startServer()
    await openApplication()

    press('Move to Screening')

    expect(await screen.findByRole('button', { name: 'Move to Interview' })).toBeInTheDocument()
    const post = server.calls.find((call) => call.method === 'POST')
    expect(post?.path).toBe('/api/applications/a1/advance')
    expect(post?.body).toEqual({ version: 1 }) // only the version: the server picks the stage
    expect(
      within(screen.getByRole('list', { name: /progress/i })).getByRole('listitem', {
        current: 'step',
      }),
    ).toHaveTextContent('Screening')
  })

  it('offers no move at the end of the line, and no buttons at all once hired', async () => {
    startServer({ application: detail({ stage: 'hired', next_stage: null }) })
    await openApplication()

    expect(screen.queryByRole('button', { name: /move to|reject/i })).not.toBeInTheDocument()
  })

  it('offers a company admin everything to read and nothing to change', async () => {
    startServer({ user: adminUser })
    await openApplication()

    expect(screen.getByText('cara@example.test')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /move to/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
  })

  it.each([
    ['rejected', 'Rejected'],
    ['withdrawn', 'Withdrawn'],
  ])('offers no action on a %s application', async (stage, label) => {
    startServer({
      application: detail({
        stage: stage as ApplicationDetail['stage'],
        next_stage: null,
        rejection:
          stage === 'rejected'
            ? { from_stage: 'screening', reason: 'skills_mismatch', comment: null }
            : null,
      }),
    })
    await openApplication()

    expect(screen.queryByRole('button', { name: /move to|reject/i })).not.toBeInTheDocument()
    expect(screen.getAllByText(label).length).toBeGreaterThan(0)
  })

  // ---- rejecting ------------------------------------------------------------------------------

  it('rejects with a reason and a comment, then shows both to staff', async () => {
    const server = startServer()
    await openApplication()

    press('Reject')
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.change(within(dialog).getByLabelText(/reason/i), {
      target: { value: 'failed_interview' },
    })
    fireEvent.change(within(dialog).getByLabelText(/comment/i), {
      target: { value: 'Struggled with the design round.' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject application' }))

    // The comment is also inside the dialog's own field until it closes: wait for that first.
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(await screen.findByText('Struggled with the design round.')).toBeInTheDocument()
    expect(screen.getByText(/failed interview/i)).toBeInTheDocument()
    const post = server.calls.find((call) => call.method === 'POST')
    expect(post?.path).toBe('/api/applications/a1/reject')
    expect(post?.body).toEqual({
      version: 1,
      reason: 'failed_interview',
      comment: 'Struggled with the design round.',
    })
    expect(screen.queryByRole('button', { name: /move to/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
  })

  it('needs a reason before it rejects anything', async () => {
    const server = startServer()
    await openApplication()
    press('Reject')
    const dialog = await screen.findByRole('alertdialog')

    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject application' }))

    expect(await within(dialog).findByText(/pick a reason/i)).toBeInTheDocument()
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('needs a comment when the reason is "other", and not otherwise', async () => {
    const server = startServer()
    await openApplication()
    press('Reject')
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.change(within(dialog).getByLabelText(/reason/i), { target: { value: 'other' } })

    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject application' }))

    expect(
      await within(dialog).findByText(/explain.*other|comment is required/i),
    ).toBeInTheDocument()
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)

    fireEvent.change(within(dialog).getByLabelText(/reason/i), {
      target: { value: 'position_filled' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject application' }))
    await waitFor(() => expect(server.calls.some((call) => call.method === 'POST')).toBe(true))
  })

  it('sends nothing if the recruiter changes their mind', async () => {
    const server = startServer()
    await openApplication()
    press('Reject')
    const dialog = await screen.findByRole('alertdialog')
    // A complete, valid form: only Cancel stands between it and a rejection.
    fireEvent.change(within(dialog).getByLabelText(/reason/i), {
      target: { value: 'skills_mismatch' },
    })

    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  })

  // ---- when someone else got there first ------------------------------------------------------

  it('says so when someone else changed the application, and reloads on request', async () => {
    const server = startServer()
    await openApplication()
    server.state.changeBehindBack = true

    press('Move to Screening')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This application was changed by someone else')
    // Nothing on screen has changed: still the stale view, with a way to get the latest.
    expect(
      within(screen.getByRole('list', { name: /progress/i })).getByRole('listitem', {
        current: 'step',
      }),
    ).toHaveTextContent('Applied')

    fireEvent.click(screen.getByRole('button', { name: /reload/i }))

    expect(await screen.findByRole('button', { name: 'Move to Interview' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the same conflict message when rejecting a stale version', async () => {
    const server = startServer()
    await openApplication()
    server.state.changeBehindBack = true
    press('Reject')
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.change(within(dialog).getByLabelText(/reason/i), {
      target: { value: 'skills_mismatch' },
    })

    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject application' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('changed by someone else')
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument()
  })

  it('shows another refusal as it is, without a reload button', async () => {
    const server = startServer()
    await openApplication()
    server.state.failNext['POST /api/applications/a1/advance'] = {
      status: 409,
      body: { detail: 'This application has ended.', code: 'application_not_active' },
    }

    press('Move to Screening')

    expect(await screen.findByRole('alert')).toHaveTextContent('This application has ended.')
  })

  // ---- who can open it, and what goes wrong -------------------------------------------------

  it('says not found for an application the server does not give them', async () => {
    startServer({ application: null })
    renderApp('/manage/applications/a1')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
  })

  it('reports a failure to load, with a way to try again', async () => {
    const server = startServer()
    server.state.failNext['GET /api/applications/a1'] = { status: 500, body: {} }
    renderApp('/manage/applications/a1')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    press(/try again/i)

    expect(await screen.findByRole('heading', { name: 'Cara Candidate' })).toBeInTheDocument()
  })

  it.each([
    ['a candidate', candidateUser],
    [
      'an interviewer',
      { ...recruiterUser, role: 'interviewer' as const, id: 'u-int', full_name: 'Ivy' },
    ],
  ])('is not a page for %s', async (_label, user) => {
    const server = startServer({ user })
    renderApp('/manage/applications/a1')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(server.calls.some((call) => call.path.startsWith('/api/applications'))).toBe(false)
  })
})

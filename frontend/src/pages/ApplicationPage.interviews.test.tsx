import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDateTime, fromLocalInputValue } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'
import type { ApplicationDetail } from './application/types'
import type { Interview, Interviewer, Scorecard } from './interviews/types'

const IVY: Interviewer = { id: 'u-ivy', full_name: 'Ivy Inman', email: 'ivy@acme.test' }
const IAN: Interviewer = { id: 'u-ian', full_name: 'Ian Ito', email: 'ian@acme.test' }

function application(stage: ApplicationDetail['stage'] = 'interview'): ApplicationDetail {
  return {
    id: 'a1',
    job_id: 'j1',
    job_title: 'Backend Engineer',
    candidate_name: 'Cara Candidate',
    candidate_email: 'cara@example.test',
    candidate_phone: null,
    candidate_location: null,
    stage,
    next_stage: stage === 'interview' ? 'offer' : null,
    version: 3,
    applied_at: '2026-11-10T09:00:00Z',
    rejection: null,
    history: [],
  }
}

function interview(overrides: Partial<Interview> = {}): Interview {
  return {
    id: 'i1',
    application_id: 'a1',
    round_name: 'Technical round',
    scheduled_at: '2030-03-05T14:30:00Z',
    duration_minutes: 60,
    location: 'Room 4',
    status: 'scheduled',
    version: 1,
    calendar_sync_status: 'not_requested',
    needs_reassignment: false,
    participants: [{ user_id: IVY.id, full_name: IVY.full_name, is_active: true }],
    created_at: '2026-11-12T09:00:00Z',
    ...overrides,
  }
}

function scorecard(overrides: Partial<Scorecard> = {}): Scorecard {
  return {
    id: 's1',
    interviewer_name: 'Ivy Inman',
    overall_rating: 4,
    technical_rating: 5,
    communication_rating: 4,
    problem_solving_rating: 3,
    culture_fit_rating: 4,
    feedback: 'Strong on systems design.',
    recommendation: 'yes',
    submitted_at: '2026-11-13T09:00:00Z',
    ...overrides,
  }
}

function startServer(
  options: {
    user?: User
    stage?: ApplicationDetail['stage']
    interviews?: Interview[]
    scorecards?: Record<string, Scorecard[]>
    interviewers?: Interviewer[]
  } = {},
) {
  const user = options.user ?? recruiterUser
  const state = {
    interviews: options.interviews ?? [],
    scorecards: options.scorecards ?? {},
    interviewers: options.interviewers ?? [IAN, IVY],
    application: application(options.stage),
    failNext: {} as Record<string, Reply>,
    // Someone else changes the interview behind the page's back before the next change.
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
    if (key === 'GET /api/applications/a1') return { status: 200, body: state.application }
    if (key === 'POST /api/applications/a1/reject') {
      // What the server does: the application ends and its scheduled interviews end with it.
      state.application = {
        ...state.application,
        stage: 'rejected',
        next_stage: null,
        version: state.application.version + 1,
      }
      for (const held of state.interviews)
        if (held.status === 'scheduled') held.status = 'cancelled'
      return { status: 200, body: state.application }
    }
    if (key === 'GET /api/applications/a1/notes') {
      return { status: 200, body: { items: [], total: 0, page: 1, page_size: 20 } }
    }
    if (key === 'GET /api/interviewers') {
      const items = state.interviewers
      return { status: 200, body: { items, total: items.length, page: 1, page_size: 100 } }
    }
    if (key === 'GET /api/applications/a1/interviews')
      return { status: 200, body: state.interviews }
    const cards = /^\/api\/interviews\/([^/]+)\/scorecards$/.exec(url.pathname)
    if (call.method === 'GET' && cards) {
      return { status: 200, body: state.scorecards[cards[1]] ?? [] }
    }
    if (key === 'POST /api/applications/a1/interviews') {
      const body = call.body as {
        round_name: string
        scheduled_at: string
        duration_minutes: number
        location: string
        interviewer_ids: string[]
      }
      const created = interview({
        id: `i${state.interviews.length + 1}`,
        round_name: body.round_name,
        scheduled_at: body.scheduled_at,
        duration_minutes: body.duration_minutes,
        location: body.location,
        participants: body.interviewer_ids.map((id) => {
          const person = state.interviewers.find((p) => p.id === id)!
          return { user_id: id, full_name: person.full_name, is_active: true }
        }),
      })
      state.interviews.push(created)
      return { status: 201, body: created }
    }
    const change = /^\/api\/interviews\/([^/]+)(?:\/(cancel))?$/.exec(url.pathname)
    if (change && call.method !== 'GET') {
      const found = state.interviews.find((i) => i.id === change[1])
      if (!found) return { status: 404, body: { detail: 'Not found.' } }
      if (state.changeBehindBack) {
        state.changeBehindBack = false
        found.version += 1
        found.location = 'Moved by a colleague'
      }
      const body = call.body as Record<string, unknown> & { version: number }
      if (body.version !== found.version) {
        return {
          status: 409,
          body: {
            detail: 'This interview was changed by someone else. Reload it and try again.',
            code: 'version_conflict',
          },
        }
      }
      if (change[2] === 'cancel') found.status = 'cancelled'
      else {
        const { interviewer_ids: ids, ...fields } = body
        delete (fields as Record<string, unknown>).version
        Object.assign(found, fields)
        if (Array.isArray(ids)) {
          found.participants = (ids as string[]).map((id) => {
            const person = state.interviewers.find((p) => p.id === id)!
            return { user_id: id, full_name: person.full_name, is_active: true }
          })
        }
      }
      found.version += 1
      return { status: 200, body: found }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

async function openPage() {
  renderApp('/manage/applications/a1')
  await screen.findByRole('heading', { name: 'Cara Candidate' })
}

function section() {
  return within(screen.getByRole('region', { name: 'Interviews' }))
}

async function openForm() {
  fireEvent.click(await screen.findByRole('button', { name: 'Schedule an interview' }))
  await screen.findByLabelText('Round name')
}

describe('ApplicationPage: interviews', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  // ---- reading ------------------------------------------------------------------------------

  it('lists the interviews with when, how long, where and who', async () => {
    startServer({ interviews: [interview()] })
    await openPage()

    const card = (await section().findByText('Technical round')).closest('li') as HTMLElement
    expect(within(card).getByText(formatDateTime('2030-03-05T14:30:00Z'))).toBeInTheDocument()
    expect(within(card).getByText(/60 minutes/)).toBeInTheDocument()
    expect(within(card).getByText(/Room 4/)).toBeInTheDocument()
    expect(within(card).getByText(/Ivy Inman/)).toBeInTheDocument()
    expect(within(card).getByText('Scheduled')).toBeInTheDocument()
  })

  it('shows what is wrong when an interviewer was deactivated after being assigned', async () => {
    startServer({
      interviews: [
        interview({
          needs_reassignment: true,
          participants: [
            { user_id: IVY.id, full_name: 'Ivy Inman', is_active: true },
            { user_id: 'u-gone', full_name: 'Gus Gone', is_active: false },
          ],
        }),
      ],
    })
    await openPage()

    expect(await section().findByText(/needs a new interviewer/i)).toBeInTheDocument()
    expect(section().getByText(/Gus Gone \(deactivated\)/)).toBeInTheDocument()
  })

  it('shows the scorecards submitted so far under each interview', async () => {
    startServer({
      interviews: [interview()],
      scorecards: { i1: [scorecard()] },
    })
    await openPage()

    expect(await section().findByText('Strong on systems design.')).toBeInTheDocument()
    expect(section().getByText(/Overall 4/)).toBeInTheDocument()
    expect(section().getByText(/Technical 5/)).toBeInTheDocument()
    expect(section().getByText('Yes')).toBeInTheDocument() // the recommendation
    expect(section().getAllByText(/Ivy Inman/).length).toBeGreaterThan(0)
  })

  it('says so when nobody has submitted a scorecard yet', async () => {
    startServer({ interviews: [interview()] })
    await openPage()

    expect(await section().findByText(/no scorecards submitted yet/i)).toBeInTheDocument()
  })

  it('shows a text-only scorecard: markup in feedback stays text', async () => {
    startServer({
      interviews: [interview()],
      scorecards: { i1: [scorecard({ feedback: '<b>Bold</b> opinion' })] },
    })
    await openPage()

    expect(await section().findByText('<b>Bold</b> opinion')).toBeInTheDocument()
    expect(document.querySelector('main b')).toBeNull()
  })

  it('says how the calendar is doing only when there is something to say', async () => {
    startServer({
      interviews: [
        interview({ id: 'i1', calendar_sync_status: 'synced' }),
        interview({ id: 'i2', round_name: 'Second', calendar_sync_status: 'failed' }),
        interview({ id: 'i3', round_name: 'Third', calendar_sync_status: 'not_requested' }),
      ],
    })
    await openPage()

    expect(await section().findByText(/calendar event created/i)).toBeInTheDocument()
    expect(section().getByText(/calendar sync failed/i)).toBeInTheDocument()
    expect(section().getAllByText(/calendar/i)).toHaveLength(2)
  })

  it('leaves the section out once the application is past the interview stage and nothing was held', async () => {
    startServer({ stage: 'offer' })
    await openPage()

    await waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Interviews' })).not.toBeInTheDocument(),
    )
  })

  it('still shows the interviews that were held when the application has moved on', async () => {
    startServer({ stage: 'offer', interviews: [interview({ status: 'completed' })] })
    await openPage()

    expect(await section().findByText('Completed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Schedule an interview' })).not.toBeInTheDocument()
  })

  // ---- who may do what ------------------------------------------------------------------------

  it('lets a company admin read everything and change nothing', async () => {
    startServer({
      user: adminUser,
      interviews: [interview()],
      scorecards: { i1: [scorecard()] },
    })
    await openPage()

    expect(await section().findByText('Strong on systems design.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Schedule an interview' })).not.toBeInTheDocument()
    expect(section().queryByRole('button', { name: 'Reschedule' })).not.toBeInTheDocument()
    expect(section().queryByRole('button', { name: 'Cancel interview' })).not.toBeInTheDocument()
  })

  it('offers no changes on a cancelled or a completed interview', async () => {
    startServer({
      interviews: [
        interview({ id: 'i1', status: 'cancelled' }),
        interview({ id: 'i2', round_name: 'Done', status: 'completed' }),
      ],
    })
    await openPage()
    await section().findByText('Done')

    expect(section().queryByRole('button', { name: 'Reschedule' })).not.toBeInTheDocument()
    expect(section().queryByRole('button', { name: 'Cancel interview' })).not.toBeInTheDocument()
  })

  it('offers scheduling only in the Interview stage', async () => {
    startServer({ stage: 'screening', interviews: [interview()] })
    await openPage()
    await section().findByText('Technical round')

    expect(screen.queryByRole('button', { name: 'Schedule an interview' })).not.toBeInTheDocument()
  })

  // ---- scheduling ------------------------------------------------------------------------------

  it('schedules an interview and shows it', async () => {
    const server = startServer()
    await openPage()
    await openForm()

    fireEvent.change(screen.getByLabelText('Round name'), { target: { value: '  Final round ' } })
    fireEvent.change(screen.getByLabelText('Date and time'), {
      target: { value: '2030-03-05T14:30' },
    })
    fireEvent.change(screen.getByLabelText('Duration (minutes)'), { target: { value: '45' } })
    fireEvent.change(screen.getByLabelText('Location'), { target: { value: 'Online' } })
    fireEvent.click(await screen.findByLabelText('Ivy Inman'))
    fireEvent.click(screen.getByLabelText('Ian Ito'))
    press('Schedule interview')

    expect(await section().findByText('Final round')).toBeInTheDocument()
    const post = server.calls.find((call) => call.method === 'POST')
    expect(post?.path).toBe('/api/applications/a1/interviews')
    expect(post?.body).toEqual({
      round_name: 'Final round',
      scheduled_at: fromLocalInputValue('2030-03-05T14:30'), // what they typed, as UTC
      duration_minutes: 45,
      location: 'Online',
      interviewer_ids: [IVY.id, IAN.id].sort(),
    })
    expect(screen.queryByLabelText('Round name')).not.toBeInTheDocument() // the form closes
  })

  it('does not send anything until the form is complete', async () => {
    const server = startServer()
    await openPage()
    await openForm()

    press('Schedule interview')

    expect(await screen.findByRole('alert')).toHaveTextContent(/round name/i)
    fireEvent.change(screen.getByLabelText('Round name'), { target: { value: 'Round' } })
    press('Schedule interview')
    expect(await screen.findByRole('alert')).toHaveTextContent(/date and time/i)
    fireEvent.change(screen.getByLabelText('Date and time'), {
      target: { value: '2030-03-05T14:30' },
    })
    fireEvent.change(screen.getByLabelText('Location'), { target: { value: 'Room' } })
    fireEvent.change(screen.getByLabelText('Duration (minutes)'), { target: { value: '2' } })
    press('Schedule interview')
    expect(await screen.findByRole('alert')).toHaveTextContent(/duration/i)
    fireEvent.change(screen.getByLabelText('Duration (minutes)'), { target: { value: '30' } })
    press('Schedule interview')
    expect(await screen.findByRole('alert')).toHaveTextContent(/at least one interviewer/i)
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('keeps the form and says why when the server refuses', async () => {
    const server = startServer()
    await openPage()
    await openForm()
    server.state.failNext['POST /api/applications/a1/interviews'] = {
      status: 409,
      body: { detail: 'Choose a time in the future.', code: 'interview_in_the_past' },
    }
    fireEvent.change(screen.getByLabelText('Round name'), { target: { value: 'Round' } })
    fireEvent.change(screen.getByLabelText('Date and time'), {
      target: { value: '2030-03-05T14:30' },
    })
    fireEvent.change(screen.getByLabelText('Location'), { target: { value: 'Room' } })
    fireEvent.click(await screen.findByLabelText('Ivy Inman'))

    press('Schedule interview')

    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a time in the future.')
    expect(screen.getByLabelText('Round name')).toHaveValue('Round') // nothing is lost
  })

  it('says so when the company has no interviewers to choose from', async () => {
    startServer({ interviewers: [] })
    await openPage()
    await openForm()

    expect(await screen.findByText(/no interviewers in your company yet/i)).toBeInTheDocument()
  })

  it('offers a retry when the interviewers cannot be loaded', async () => {
    const server = startServer()
    server.state.failNext['GET /api/interviewers'] = { status: 500, body: {} }
    await openPage()
    await openForm()

    fireEvent.click(await screen.findByRole('button', { name: /try again/i }))

    expect(await screen.findByLabelText('Ivy Inman')).toBeInTheDocument()
  })

  it('can be closed without sending anything', async () => {
    const server = startServer()
    await openPage()
    await openForm()

    press('Discard')

    expect(screen.queryByLabelText('Round name')).not.toBeInTheDocument()
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  // ---- rescheduling ------------------------------------------------------------------------------

  it('reschedules, sending only what changed and the version', async () => {
    const server = startServer({ interviews: [interview({ version: 4 })] })
    await openPage()
    await section().findByText('Technical round')

    fireEvent.click(section().getByRole('button', { name: 'Reschedule' }))
    expect(await screen.findByLabelText('Location')).toHaveValue('Room 4') // starts from what is there
    fireEvent.change(screen.getByLabelText('Location'), { target: { value: 'Room 9' } })
    press('Save changes')

    expect(await section().findByText(/Room 9/)).toBeInTheDocument()
    const patch = server.calls.find((call) => call.method === 'PATCH')
    expect(patch?.path).toBe('/api/interviews/i1')
    expect(patch?.body).toEqual({ version: 4, location: 'Room 9' })
  })

  it('sends the new interviewers when the people change', async () => {
    const server = startServer({ interviews: [interview()] })
    await openPage()
    await section().findByText('Technical round')

    fireEvent.click(section().getByRole('button', { name: 'Reschedule' }))
    fireEvent.click(await screen.findByLabelText('Ian Ito'))
    press('Save changes')

    await section().findByText(/Ian Ito/)
    const patch = server.calls.find((call) => call.method === 'PATCH')
    expect(patch?.body).toEqual({ version: 1, interviewer_ids: [IAN.id, IVY.id].sort() })
  })

  it('sends nothing when nothing was changed', async () => {
    const server = startServer({ interviews: [interview()] })
    await openPage()
    await section().findByText('Technical round')
    fireEvent.click(section().getByRole('button', { name: 'Reschedule' }))
    await screen.findByLabelText('Location')

    press('Save changes')

    await waitFor(() => expect(screen.queryByLabelText('Location')).not.toBeInTheDocument())
    expect(server.calls.some((call) => call.method === 'PATCH')).toBe(false)
  })

  // ---- cancelling -----------------------------------------------------------------------------------

  it('asks before cancelling, and sends nothing if the recruiter keeps it', async () => {
    const server = startServer({ interviews: [interview()] })
    await openPage()
    await section().findByText('Technical round')

    fireEvent.click(section().getByRole('button', { name: 'Cancel interview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Keep interview' }))

    expect(
      server.calls.some((call) => call.method === 'POST' && call.path.includes('cancel')),
    ).toBe(false)
    expect(section().getByText('Scheduled')).toBeInTheDocument()
  })

  it('cancels once confirmed and shows the interview as cancelled', async () => {
    const server = startServer({ interviews: [interview({ version: 2 })] })
    await openPage()
    await section().findByText('Technical round')

    fireEvent.click(section().getByRole('button', { name: 'Cancel interview' }))
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel interview' }))

    expect(await section().findByText('Cancelled')).toBeInTheDocument()
    const post = server.calls.find((call) => call.path === '/api/interviews/i1/cancel')
    expect(post?.body).toEqual({ version: 2 })
    expect(section().queryByRole('button', { name: 'Cancel interview' })).not.toBeInTheDocument()
  })

  // ---- when someone else got there first ----------------------------------------------------------------

  it('says so when someone else changed the interview, and reloads on request', async () => {
    const server = startServer({ interviews: [interview()] })
    await openPage()
    await section().findByText('Technical round')
    server.state.changeBehindBack = true

    fireEvent.click(section().getByRole('button', { name: 'Cancel interview' }))
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel interview' }))

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument()
    expect(section().queryByText('Cancelled')).not.toBeInTheDocument() // still the stale view
    fireEvent.click(screen.getByRole('button', { name: /reload/i }))
    expect(await section().findByText(/Moved by a colleague/)).toBeInTheDocument()
    expect(screen.queryByText(/changed by someone else/i)).not.toBeInTheDocument()
  })

  it('shows the same conflict message when rescheduling a stale interview', async () => {
    const server = startServer({ interviews: [interview()] })
    await openPage()
    await section().findByText('Technical round')
    server.state.changeBehindBack = true

    fireEvent.click(section().getByRole('button', { name: 'Reschedule' }))
    fireEvent.change(await screen.findByLabelText('Location'), { target: { value: 'Room 9' } })
    press('Save changes')

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument()
  })

  it('shows the interviews as cancelled, without a reload, once the application is rejected', async () => {
    startServer({ interviews: [interview()] })
    await openPage()
    await section().findByText('Scheduled')

    press('Reject')
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.change(within(dialog).getByLabelText(/reason/i), {
      target: { value: 'skills_mismatch' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject application' }))

    // The page behind the dialog is hidden from the accessibility tree until it has closed.
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(await section().findByText('Cancelled')).toBeInTheDocument()
    expect(section().queryByRole('button', { name: 'Reschedule' })).not.toBeInTheDocument()
  })

  // ---- the section on its own -------------------------------------------------------------------------------

  it('keeps the rest of the page working when the interviews fail to load, and can retry', async () => {
    const server = startServer({ interviews: [interview()] })
    server.state.failNext['GET /api/applications/a1/interviews'] = { status: 500, body: {} }
    await openPage()

    expect(await section().findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /move to offer/i })).toBeInTheDocument() // page intact
    fireEvent.click(section().getByRole('button', { name: /try again/i }))

    expect(await section().findByText('Technical round')).toBeInTheDocument()
  })
})

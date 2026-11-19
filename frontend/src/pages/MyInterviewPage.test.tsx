import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDateTime } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, candidateUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'
import type { MyInterviewDetail, Scorecard } from './interviews/types'

const interviewerUser: User = {
  id: 'u-ivy',
  email: 'ivy@acme.test',
  full_name: 'Ivy Inman',
  role: 'interviewer',
  company_id: 'c-1',
  email_verified_at: '2026-01-01T09:00:00Z',
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

function detail(overrides: Partial<MyInterviewDetail> = {}): MyInterviewDetail {
  return {
    id: 'i1',
    round_name: 'Technical round',
    scheduled_at: '2030-03-05T14:30:00Z',
    duration_minutes: 60,
    location: 'Room 4',
    status: 'scheduled',
    job_title: 'Backend Engineer',
    candidate: {
      name: 'Cara Candidate',
      email: 'cara@example.test',
      phone: '+47 123 45 678',
      location: 'Oslo',
    },
    my_scorecard: null,
    others_visible: false,
    others: [],
    ...overrides,
  }
}

function startServer(options: { user?: User; interview?: MyInterviewDetail | null } = {}) {
  const user = options.user ?? interviewerUser
  const state = {
    interview: options.interview === undefined ? detail() : options.interview,
    // What the real server does when the interviewer submits: their scorecard appears, and with it
    // the colleagues' (here, one who had already submitted).
    colleagues: [scorecard({ id: 's2', interviewer_name: 'Ian Ito', feedback: 'Ian says hello.' })],
    failNext: {} as Record<string, Reply>,
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
    if (key === 'GET /api/my/interviews/i1') {
      if (state.interview === null) return { status: 404, body: { detail: 'Not found.' } }
      return { status: 200, body: state.interview }
    }
    if (key === 'POST /api/my/interviews/i1/scorecard' && state.interview) {
      const body = call.body as Omit<Scorecard, 'id' | 'interviewer_name' | 'submitted_at'>
      const mine = scorecard({
        ...body,
        id: 's1',
        interviewer_name: user.full_name,
        submitted_at: '2026-11-14T09:00:00Z',
      })
      state.interview = {
        ...state.interview,
        my_scorecard: mine,
        others_visible: true,
        others: state.colleagues,
      }
      return { status: 201, body: mine }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

async function openPage() {
  renderApp('/interviews/i1')
  await screen.findByRole('heading', { name: 'Technical round' })
}

function fillForm(overrides: Record<string, string> = {}) {
  const values: Record<string, string> = {
    'Overall rating': '4',
    'Technical skills': '5',
    Communication: '4',
    'Problem solving': '3',
    'Culture and team fit': '4',
    Recommendation: 'yes',
    Feedback: 'Strong on systems design.',
    ...overrides,
  }
  for (const [label, value] of Object.entries(values)) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } })
  }
}

describe('MyInterviewPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  // ---- reading --------------------------------------------------------------------------------

  it('shows the interview and the candidate, with the resume to download', async () => {
    startServer()
    await openPage()

    expect(screen.getByText(formatDateTime('2030-03-05T14:30:00Z'))).toBeInTheDocument()
    expect(screen.getByText(/60 minutes/)).toBeInTheDocument()
    expect(screen.getByText(/Room 4/)).toBeInTheDocument()
    expect(screen.getByText(/Backend Engineer/)).toBeInTheDocument()
    expect(screen.getByText('Cara Candidate')).toBeInTheDocument()
    expect(screen.getByText('cara@example.test')).toBeInTheDocument()
    expect(screen.getByText('+47 123 45 678')).toBeInTheDocument()
    expect(screen.getByText('Oslo')).toBeInTheDocument()
    const resume = screen.getByRole('link', { name: /download resume/i })
    expect(resume).toHaveAttribute('href', '/api/my/interviews/i1/resume')
    expect(resume).toHaveAttribute('target', '_blank')
    expect(resume).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('shows the candidate’s name as text, never as markup', async () => {
    startServer({
      interview: detail({
        candidate: { name: '<b>Bold</b> Bob', email: 'b@x.test', phone: null, location: null },
      }),
    })
    await openPage()

    expect(screen.getByText('<b>Bold</b> Bob')).toBeInTheDocument()
    expect(document.querySelector('main b')).toBeNull()
  })

  it('shows no candidate and no resume once the interview is cancelled', async () => {
    startServer({ interview: detail({ status: 'cancelled', candidate: null }) })
    await openPage()

    expect(screen.queryByText('Cara Candidate')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /download resume/i })).not.toBeInTheDocument()
    expect(screen.getByText('Cancelled')).toBeInTheDocument()
    expect(screen.getByText(/no scorecard can be submitted/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Feedback')).not.toBeInTheDocument()
  })

  it('says so when the interview is not one of theirs', async () => {
    startServer({ interview: null })
    renderApp('/interviews/i1')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
  })

  it('reports a failure to load, with a way to try again', async () => {
    const server = startServer()
    server.state.failNext['GET /api/my/interviews/i1'] = { status: 500, body: {} }
    renderApp('/interviews/i1')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    press(/try again/i)

    expect(await screen.findByRole('heading', { name: 'Technical round' })).toBeInTheDocument()
  })

  it.each([
    ['a recruiter', recruiterUser],
    ['a company admin', adminUser],
    ['a candidate', candidateUser],
  ])('is not a page for %s', async (_label, user) => {
    const server = startServer({ user })
    renderApp('/interviews/i1')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(server.calls.some((call) => call.path.startsWith('/api/my/interviews'))).toBe(false)
  })

  // ---- blind scoring, as the screen shows it ----------------------------------------------------------

  it('explains blind scoring and shows nobody else’s scorecard before the interviewer submits', async () => {
    startServer()
    await openPage()

    expect(screen.getByText(/colleagues.*scorecards.*after you submit/i)).toBeInTheDocument()
    expect(screen.queryByText('Ian says hello.')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /colleagues/i })).not.toBeInTheDocument()
  })

  it('shows the interviewer’s own scorecard and their colleagues’ once they have submitted', async () => {
    startServer({
      interview: detail({
        my_scorecard: scorecard({ feedback: 'My own view.' }),
        others_visible: true,
        others: [scorecard({ id: 's2', interviewer_name: 'Ian Ito', feedback: 'Ian’s view.' })],
      }),
    })
    await openPage()

    expect(screen.getByText('My own view.')).toBeInTheDocument()
    expect(screen.getByText('Ian’s view.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Feedback')).not.toBeInTheDocument() // no second submission
  })

  it('says so when nobody else has submitted yet', async () => {
    startServer({
      interview: detail({ my_scorecard: scorecard(), others_visible: true, others: [] }),
    })
    await openPage()

    expect(await screen.findByText(/no colleague has submitted yet/i)).toBeInTheDocument()
  })

  it('shows scorecard text as text, never as markup', async () => {
    startServer({
      interview: detail({
        my_scorecard: scorecard({ feedback: '<b>Bold</b> opinion' }),
        others_visible: true,
      }),
    })
    await openPage()

    expect(screen.getByText('<b>Bold</b> opinion')).toBeInTheDocument()
    expect(document.querySelector('main b')).toBeNull()
  })

  // ---- submitting ------------------------------------------------------------------------------------------

  it('submits a scorecard after a confirmation, then shows it with the colleagues’', async () => {
    const server = startServer()
    await openPage()

    fillForm({ Feedback: '  Strong on systems design.  ', Recommendation: 'strong_yes' })
    press('Submit scorecard')
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent(/cannot be changed/i)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Yes, submit' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(await screen.findByText('Ian says hello.')).toBeInTheDocument() // the colleagues'
    expect(screen.getByText('Strong on systems design.')).toBeInTheDocument() // their own
    expect(screen.queryByLabelText('Feedback')).not.toBeInTheDocument()
    const post = server.calls.find((call) => call.method === 'POST')
    expect(post?.path).toBe('/api/my/interviews/i1/scorecard')
    expect(post?.body).toEqual({
      overall_rating: 4,
      technical_rating: 5,
      communication_rating: 4,
      problem_solving_rating: 3,
      culture_fit_rating: 4,
      feedback: 'Strong on systems design.', // trimmed
      recommendation: 'strong_yes',
    })
  })

  it('asks before sending, and sends nothing if the interviewer keeps editing', async () => {
    const server = startServer()
    await openPage()
    fillForm()

    press('Submit scorecard')
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep editing' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
    expect(screen.getByLabelText('Feedback')).toHaveValue('Strong on systems design.')
  })

  it.each([
    ['Overall rating', /overall rating/i],
    ['Technical skills', /technical/i],
    ['Communication', /communication/i],
    ['Problem solving', /problem solving/i],
    ['Culture and team fit', /culture/i],
    ['Recommendation', /recommendation/i],
  ])('does not send until %s is chosen', async (label, message) => {
    const server = startServer()
    await openPage()
    fillForm({ [label]: '' })

    press('Submit scorecard')

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('does not send blank feedback', async () => {
    const server = startServer()
    await openPage()
    fillForm({ Feedback: '   ' })

    press('Submit scorecard')

    expect(await screen.findByRole('alert')).toHaveTextContent(/feedback/i)
    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('limits the feedback to the length the server accepts', async () => {
    startServer()
    await openPage()

    expect(screen.getByLabelText('Feedback')).toHaveAttribute('maxlength', '4000')
  })

  it('keeps what was typed and says why when the server refuses', async () => {
    const server = startServer()
    await openPage()
    server.state.failNext['POST /api/my/interviews/i1/scorecard'] = {
      status: 409,
      body: { detail: 'This interview is no longer scheduled.', code: 'interview_not_scheduled' },
    }
    fillForm({ Feedback: 'Do not lose me' })

    press('Submit scorecard')
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Yes, submit' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This interview is no longer scheduled.',
    )
    expect(screen.getByLabelText('Feedback')).toHaveValue('Do not lose me')
  })

  it('moves to the submitted view if the server says the scorecard was already in', async () => {
    // Two tabs, or a retry: the first one got through. Nothing is lost, and nothing is sent twice.
    const server = startServer()
    await openPage()
    fillForm()
    server.state.failNext['POST /api/my/interviews/i1/scorecard'] = {
      status: 409,
      body: { detail: 'You have already submitted.', code: 'scorecard_already_submitted' },
    }
    server.state.interview = detail({
      my_scorecard: scorecard({ feedback: 'Submitted in the other tab.' }),
      others_visible: true,
    })

    press('Submit scorecard')
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Yes, submit' }),
    )

    expect(await screen.findByText('Submitted in the other tab.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Feedback')).not.toBeInTheDocument()
  })

  it('switches the button off while the scorecard is being sent', async () => {
    startServer()
    await openPage()
    fillForm()

    press('Submit scorecard')
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Yes, submit' }),
    )

    // Straight after the click, while the request runs. The page behind the closing dialog is
    // still hidden from the accessibility tree, hence `hidden`.
    expect(screen.getByRole('button', { name: 'Submit scorecard', hidden: true })).toBeDisabled()
    await screen.findByText('Ian says hello.')
  })
})

import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDateTime } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, candidateUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'
import type { MyInterviewRow } from './interviews/types'

const interviewerUser: User = {
  id: 'u-ivy',
  email: 'ivy@acme.test',
  full_name: 'Ivy Inman',
  role: 'interviewer',
  company_id: 'c-1',
  email_verified_at: '2026-01-01T09:00:00Z',
}

function row(overrides: Partial<MyInterviewRow> = {}): MyInterviewRow {
  return {
    id: 'i1',
    round_name: 'Technical round',
    scheduled_at: '2030-03-05T14:30:00Z',
    duration_minutes: 60,
    location: 'Room 4',
    status: 'scheduled',
    job_title: 'Backend Engineer',
    candidate_name: 'Cara Candidate',
    my_scorecard_submitted: false,
    ...overrides,
  }
}

type Lists = { awaiting?: MyInterviewRow[]; upcoming?: MyInterviewRow[]; all?: MyInterviewRow[] }

function startServer(options: { user?: User; lists?: Lists } = {}) {
  const user = options.user ?? interviewerUser
  const lists = options.lists ?? {}
  const state = { failNext: {} as Record<string, Reply> }

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
    if (key === 'GET /api/my/interviews') {
      const which = (url.searchParams.get('filter') ?? 'all') as keyof Lists
      const everything = lists[which] ?? []
      const page = Number(url.searchParams.get('page') ?? '1')
      const size = Number(url.searchParams.get('page_size') ?? '20')
      const items = everything.slice((page - 1) * size, page * size)
      return { status: 200, body: { items, total: everything.length, page, page_size: size } }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

describe('MyInterviewsPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('opens on what needs the interviewer’s scorecard', async () => {
    const server = startServer({ lists: { awaiting: [row()] } })
    renderApp('/interviews')

    expect(await screen.findByText('Technical round')).toBeInTheDocument()
    const first = server.calls.find((call) => call.path.startsWith('/api/my/interviews'))
    expect(first?.path).toContain('filter=awaiting')
    expect(screen.getByRole('button', { name: 'Awaiting my scorecard' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('shows each interview with its time, job, candidate and what is still to do', async () => {
    startServer({ lists: { awaiting: [row()] } })
    renderApp('/interviews')

    const card = (await screen.findByText('Technical round')).closest('li') as HTMLElement
    expect(within(card).getByText(formatDateTime('2030-03-05T14:30:00Z'))).toBeInTheDocument()
    expect(within(card).getByText(/Backend Engineer/)).toBeInTheDocument()
    expect(within(card).getByText(/Cara Candidate/)).toBeInTheDocument()
    expect(within(card).getByText(/60 minutes/)).toBeInTheDocument()
    expect(within(card).getByText('Scorecard needed')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'Technical round' })).toHaveAttribute(
      'href',
      '/interviews/i1',
    )
  })

  it('shows what has been done and what has ended', async () => {
    startServer({
      lists: {
        all: [
          row({ id: 'i1', my_scorecard_submitted: true }),
          row({ id: 'i2', round_name: 'Called off', status: 'cancelled', candidate_name: null }),
          row({ id: 'i3', round_name: 'Done', status: 'completed', my_scorecard_submitted: true }),
        ],
      },
    })
    renderApp('/interviews')
    fireEvent.click(await screen.findByRole('button', { name: 'All my interviews' }))

    const cancelled = (await screen.findByText('Called off')).closest('li') as HTMLElement
    expect(within(cancelled).getByText('Cancelled')).toBeInTheDocument()
    expect(within(cancelled).queryByText(/Candidate/)).not.toBeInTheDocument() // not shown any more
    expect(within(cancelled).queryByText(/Scorecard/)).not.toBeInTheDocument()
    expect(screen.getAllByText('Scorecard submitted')).toHaveLength(2)
    expect(
      within((await screen.findByText('Done')).closest('li') as HTMLElement).getByText('Completed'),
    ).toBeInTheDocument()
  })

  it('switches between awaiting, upcoming and everything, asking the server each time', async () => {
    const server = startServer({
      lists: {
        awaiting: [row({ id: 'i1', round_name: 'Needs me' })],
        upcoming: [row({ id: 'i2', round_name: 'Next week' })],
        all: [row({ id: 'i3', round_name: 'Long ago' })],
      },
    })
    renderApp('/interviews')
    await screen.findByText('Needs me')

    press('Upcoming')
    expect(await screen.findByText('Next week')).toBeInTheDocument()
    expect(screen.queryByText('Needs me')).not.toBeInTheDocument()
    press('All my interviews')
    expect(await screen.findByText('Long ago')).toBeInTheDocument()

    const filters = server.calls
      .filter((call) => call.path.startsWith('/api/my/interviews'))
      .map((call) => new URL(call.path, 'http://app.test').searchParams.get('filter'))
    expect(filters).toEqual(expect.arrayContaining(['awaiting', 'upcoming', 'all']))
  })

  it.each([
    ['Awaiting my scorecard', /nothing is waiting for your scorecard/i],
    ['Upcoming', /no upcoming interviews/i],
    ['All my interviews', /not been assigned to any interview/i],
  ])('says something kind when the %s list is empty', async (button, message) => {
    startServer()
    renderApp('/interviews')
    await screen.findByRole('button', { name: 'Awaiting my scorecard' })

    press(button)

    expect(await screen.findByText(message)).toBeInTheDocument()
  })

  it('pages through a long list', async () => {
    const many = Array.from({ length: 21 }, (_, index) =>
      row({ id: `i${index}`, round_name: `Round ${index}` }),
    )
    startServer({ lists: { awaiting: many } })
    renderApp('/interviews')
    await screen.findByText('Round 0')
    expect(screen.queryByText('Round 20')).not.toBeInTheDocument()

    press('Next')

    expect(await screen.findByText('Round 20')).toBeInTheDocument()
  })

  it('starts from the first page when another list is chosen', async () => {
    const many = Array.from({ length: 21 }, (_, index) =>
      row({ id: `i${index}`, round_name: `Round ${index}` }),
    )
    const server = startServer({
      lists: { awaiting: many, upcoming: [row({ round_name: 'Coming soon' })] },
    })
    renderApp('/interviews')
    await screen.findByText('Round 0')
    press('Next') // page 2 of the awaiting list
    await screen.findByText('Round 20')

    press('Upcoming')

    expect(await screen.findByText('Coming soon')).toBeInTheDocument()
    const last = server.calls.filter((call) => call.path.startsWith('/api/my/interviews')).at(-1)
    const params = new URL(last!.path, 'http://app.test').searchParams
    expect(params.get('filter')).toBe('upcoming')
    expect(params.get('page')).toBe('1')
  })

  it('reports a failure to load, with a way to try again', async () => {
    const server = startServer({ lists: { awaiting: [row()] } })
    server.state.failNext['GET /api/my/interviews'] = { status: 500, body: {} }
    renderApp('/interviews')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    press(/try again/i)

    expect(await screen.findByText('Technical round')).toBeInTheDocument()
  })

  it('is in the menu for an interviewer, and it is where they land after logging in', async () => {
    startServer({ lists: { awaiting: [row()] } })
    renderApp('/')

    expect(await screen.findByRole('link', { name: 'My interviews' })).toHaveAttribute(
      'href',
      '/interviews',
    )
  })

  it('takes an interviewer who is logged in straight from the login page to their interviews', async () => {
    startServer({ lists: { awaiting: [row()] } })
    renderApp('/login')

    expect(await screen.findByRole('heading', { name: 'My interviews' })).toBeInTheDocument()
    expect(await screen.findByText('Technical round')).toBeInTheDocument()
  })

  it.each([
    ['a recruiter', recruiterUser],
    ['a company admin', adminUser],
    ['a candidate', candidateUser],
  ])('is not a page for %s', async (_label, user) => {
    const server = startServer({ user })
    renderApp('/interviews')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(server.calls.some((call) => call.path.startsWith('/api/my/interviews'))).toBe(false)
  })
})

import { screen, waitFor, within } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'

interface JobRow {
  id: string
  title: string
  location: string
  status: 'draft' | 'open' | 'closed'
  department_id: string
  department_name: string
  created_at: string
  opened_at: string | null
  closed_at: string | null
  version: number
  needs_reassignment: boolean
}

function job(id: string, title: string, extra: Partial<JobRow> = {}): JobRow {
  return {
    id,
    title,
    location: 'Remote',
    status: 'draft',
    department_id: 'dep-eng',
    department_name: 'Engineering',
    created_at: '2026-11-01T12:00:00Z',
    opened_at: null,
    closed_at: null,
    version: 1,
    needs_reassignment: false,
    ...extra,
  }
}

const DEPARTMENTS = [
  { id: 'dep-eng', name: 'Engineering', is_archived: false },
  { id: 'dep-old', name: 'Old team', is_archived: true },
]

/** A little in-memory company that answers the way the real server does. */
function startServer(jobs: JobRow[], user = adminUser) {
  const state = { jobs, failNext: {} as Record<string, Reply> }

  const backend = stubBackend((call) => {
    const url = new URL(call.path, 'http://app.test')
    const planned = state.failNext[`${call.method} ${url.pathname}`]
    if (planned) {
      delete state.failNext[`${call.method} ${url.pathname}`]
      return planned
    }
    if (url.pathname === '/api/auth/me') return { status: 200, body: sessionFor(user) }
    if (url.pathname === '/health') return { status: 200, body: { status: 'ok' } }
    if (url.pathname === '/api/departments') {
      return {
        status: 200,
        body: { items: DEPARTMENTS, total: DEPARTMENTS.length, page: 1, page_size: 100 },
      }
    }
    if (url.pathname === '/api/jobs' && call.method === 'GET') {
      const status = url.searchParams.get('status')
      const departmentId = url.searchParams.get('department_id')
      const page = Number(url.searchParams.get('page') ?? '1')
      const pageSize = Number(url.searchParams.get('page_size') ?? '20')
      const matching = state.jobs.filter(
        (j) =>
          (!status || j.status === status) && (!departmentId || j.department_id === departmentId),
      )
      const start = (page - 1) * pageSize
      return {
        status: 200,
        body: {
          items: matching.slice(start, start + pageSize),
          total: matching.length,
          page,
          page_size: pageSize,
        },
      }
    }
    throw new Error(`Unplanned request in test: ${call.method} ${call.path}`)
  })

  return { state, calls: backend.calls }
}

function rowOf(title: string) {
  return within(screen.getByRole('row', { name: new RegExp(title) }))
}

function jobsRequests(calls: { path: string }[]) {
  return calls.filter((c) => c.path.startsWith('/api/jobs')).map((c) => new URL(c.path, 'http://x'))
}

describe('JobsPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists jobs with their department, status and the day they opened', async () => {
    startServer([
      job('j1', 'Backend Engineer', {
        status: 'open',
        opened_at: '2026-11-03T12:00:00Z',
      }),
      job('j2', 'Designer', { status: 'draft' }),
      job('j3', 'Old role', { status: 'closed', opened_at: '2026-01-05T12:00:00Z' }),
    ])
    renderApp('/manage/jobs')

    expect(await screen.findByRole('heading', { name: 'Jobs' })).toBeInTheDocument()
    await screen.findByRole('table', { name: /jobs/i })
    expect(rowOf('Backend Engineer').getByText('Open')).toBeInTheDocument()
    expect(rowOf('Backend Engineer').getByText('Engineering')).toBeInTheDocument()
    expect(
      rowOf('Backend Engineer').getByText(formatDate('2026-11-03T12:00:00Z')),
    ).toBeInTheDocument()
    expect(rowOf('Designer').getByText('Draft')).toBeInTheDocument()
    expect(rowOf('Old role').getByText('Closed')).toBeInTheDocument()
  })

  it('flags a job that has no active recruiter', async () => {
    startServer([job('j1', 'Covered'), job('j2', 'Orphaned', { needs_reassignment: true })])
    renderApp('/manage/jobs')
    await screen.findByRole('table', { name: /jobs/i })

    expect(rowOf('Orphaned').getByText(/needs a recruiter/i)).toBeInTheDocument()
    expect(rowOf('Covered').queryByText(/needs a recruiter/i)).not.toBeInTheDocument()
  })

  it('shows job titles as text, never as HTML', async () => {
    startServer([job('j1', '<img src=x onerror=alert(1)>')])
    renderApp('/manage/jobs')

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('main img')).toBeNull()
  })

  it('offers a link to create a job', async () => {
    startServer([])
    renderApp('/manage/jobs')

    const link = await screen.findByRole('link', { name: /new job/i })
    expect(link).toHaveAttribute('href', '/manage/jobs/new')
  })

  it('tells an admin and a recruiter apart when there are no jobs', async () => {
    startServer([])
    const { unmount } = renderApp('/manage/jobs')
    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/assigned to you/i)).not.toBeInTheDocument()
    unmount()
    vi.unstubAllGlobals()

    startServer([], recruiterUser)
    renderApp('/manage/jobs')
    expect(await screen.findByText(/no jobs assigned to you yet/i)).toBeInTheDocument()
  })

  it('tells a recruiter that the list holds the jobs assigned to them', async () => {
    startServer([job('j1', 'Mine')], recruiterUser)
    renderApp('/manage/jobs')

    expect(await screen.findByRole('heading', { name: 'My jobs' })).toBeInTheDocument()
    expect(screen.getByText(/jobs assigned to you/i)).toBeInTheDocument()
  })

  it('says so when the list cannot be loaded, and lets the user try again', async () => {
    const server = startServer([job('j1', 'Backend Engineer')])
    server.state.failNext['GET /api/jobs'] = { status: 500 }
    renderApp('/manage/jobs')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByRole('table', { name: /jobs/i })).toBeInTheDocument()
  })
})

describe('JobsPage: filters and paging', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('filters by status and shows only matching jobs', async () => {
    const { calls } = startServer([
      job('j1', 'Open one', { status: 'open' }),
      job('j2', 'Draft one', { status: 'draft' }),
    ])
    renderApp('/manage/jobs')
    await screen.findByRole('table', { name: /jobs/i })

    fireEvent.change(screen.getByLabelText(/^status$/i), { target: { value: 'open' } })

    await waitFor(() => expect(screen.queryByText('Draft one')).not.toBeInTheDocument())
    expect(screen.getByText('Open one')).toBeInTheDocument()
    expect(jobsRequests(calls).at(-1)?.searchParams.get('status')).toBe('open')
  })

  it('filters by department, including archived ones', async () => {
    const { calls } = startServer([
      job('j1', 'Engineering job'),
      job('j2', 'Old team job', { department_id: 'dep-old', department_name: 'Old team' }),
    ])
    renderApp('/manage/jobs')
    await screen.findByRole('table', { name: /jobs/i })

    fireEvent.change(screen.getByLabelText(/^department$/i), { target: { value: 'dep-old' } })

    await waitFor(() => expect(screen.queryByText('Engineering job')).not.toBeInTheDocument())
    expect(screen.getByText('Old team job')).toBeInTheDocument()
    expect(jobsRequests(calls).at(-1)?.searchParams.get('department_id')).toBe('dep-old')
  })

  it('says when no job matches the filters, and lets the user clear them', async () => {
    startServer([job('j1', 'Draft one', { status: 'draft' })])
    renderApp('/manage/jobs')
    await screen.findByRole('table', { name: /jobs/i })

    fireEvent.change(screen.getByLabelText(/^status$/i), { target: { value: 'closed' } })

    expect(await screen.findByText(/no jobs match/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/^status$/i), { target: { value: '' } })
    expect(await screen.findByText('Draft one')).toBeInTheDocument()
  })

  it('shows one page at a time, and goes back to page 1 when a filter changes', async () => {
    const many = Array.from({ length: 45 }, (_, n) =>
      job(`j${n}`, `Job ${String(n).padStart(2, '0')}`, { status: n % 2 === 0 ? 'open' : 'draft' }),
    )
    const { calls } = startServer(many)
    renderApp('/manage/jobs')

    expect(await screen.findByText('Job 00')).toBeInTheDocument()
    expect(screen.getByText(/page 1 of 3/i)).toBeInTheDocument()
    press(/next/i)
    expect(await screen.findByText('Job 20')).toBeInTheDocument()
    expect(screen.getByText(/page 2 of 3/i)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/^status$/i), { target: { value: 'open' } })

    await waitFor(() => expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument())
    const last = jobsRequests(calls).at(-1)!
    expect(last.searchParams.get('page')).toBe('1')
    expect(last.searchParams.get('status')).toBe('open')
  })
})

describe('JobsPage: who may open it', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows an interviewer "not found" and never asks for the list', async () => {
    const interviewer = { ...recruiterUser, id: 'u-int', role: 'interviewer' as const }
    const { calls } = startServer([job('j1', 'Backend Engineer')], interviewer)
    renderApp('/manage/jobs')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(jobsRequests(calls)).toEqual([])
  })

  it('gives an admin a Jobs link and a recruiter a My jobs link', async () => {
    startServer([])
    const { unmount } = renderApp('/')
    expect(await screen.findByRole('link', { name: 'Jobs' })).toHaveAttribute(
      'href',
      '/manage/jobs',
    )
    unmount()
    vi.unstubAllGlobals()

    startServer([], recruiterUser)
    renderApp('/')
    expect(await screen.findByRole('link', { name: 'My jobs' })).toHaveAttribute(
      'href',
      '/manage/jobs',
    )
  })
})

import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

interface PublicJob {
  id: string
  title: string
  location: string
  excerpt: string
  department_name: string
  company_id: string
  company_name: string
  opened_at: string | null
}

function publicJob(id: string, title: string, extra: Partial<PublicJob> = {}): PublicJob {
  return {
    id,
    title,
    location: 'Remote',
    excerpt: 'Build and run our services.',
    department_name: 'Engineering',
    company_id: 'c-acme',
    company_name: 'Acme',
    opened_at: '2026-11-05T12:00:00Z',
    ...extra,
  }
}

/** The public side of a little server: it filters the way the real one does, roughly. */
function startServer(jobs: PublicJob[], options: { loggedIn?: boolean } = {}) {
  const state = { jobs, failNext: {} as Record<string, Reply> }

  const backend = stubBackend((call) => {
    const url = new URL(call.path, 'http://app.test')
    const key = `${call.method} ${url.pathname}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /api/auth/me') {
      return options.loggedIn
        ? { status: 200, body: sessionFor(recruiterUser) }
        : { status: 401, body: { detail: 'Not logged in.' } }
    }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/public/jobs') {
      const q = (url.searchParams.get('q') ?? '').toLowerCase()
      const location = (url.searchParams.get('location') ?? '').toLowerCase()
      const company = url.searchParams.get('company_id')
      const page = Number(url.searchParams.get('page') ?? '1')
      const pageSize = Number(url.searchParams.get('page_size') ?? '20')
      const matching = state.jobs.filter(
        (j) =>
          (!q || j.title.toLowerCase().includes(q)) &&
          (!location || j.location.toLowerCase().includes(location)) &&
          (!company || j.company_id === company),
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
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function searches(calls: { path: string }[]) {
  return calls
    .filter((c) => c.path.startsWith('/api/public/jobs'))
    .map((c) => new URL(c.path, 'http://x').searchParams)
}

function resetBrowserState() {
  setCsrfToken(null)
  setUnauthorizedHandler(null)
}

describe('PublicJobsPage', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('lets a visitor who is not logged in see open jobs', async () => {
    startServer([
      publicJob('j1', 'Backend Engineer', { location: 'Oslo' }),
      publicJob('j2', 'Designer', { company_id: 'c-globex', company_name: 'Globex' }),
    ])
    renderApp('/jobs')

    expect(await screen.findByRole('heading', { name: /find a job/i })).toBeInTheDocument()
    const first = within(await screen.findByRole('article', { name: /backend engineer/i }))
    expect(first.getByRole('link', { name: 'Backend Engineer' })).toHaveAttribute(
      'href',
      '/jobs/j1',
    )
    expect(first.getByText('Acme')).toBeInTheDocument()
    expect(first.getByText(/engineering/i)).toBeInTheDocument()
    expect(first.getByText(/oslo/i)).toBeInTheDocument()
    expect(first.getByText('Build and run our services.')).toBeInTheDocument()
    expect(first.getByText(formatDate('2026-11-05T12:00:00Z'))).toBeInTheDocument()
    expect(screen.getByRole('article', { name: /designer/i })).toBeInTheDocument()
    expect(screen.getByText(/2 jobs found/i)).toBeInTheDocument()
  })

  it('shows job text as text, never as HTML', async () => {
    startServer([
      publicJob('j1', '<img src=x onerror=alert(1)>', {
        excerpt: '<b>bold</b>',
        company_name: '<i>Co</i>',
      }),
    ])
    renderApp('/jobs')

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(screen.getByText('<b>bold</b>')).toBeInTheDocument()
    expect(document.querySelector('main img, main b, main i')).toBeNull()
  })

  it('works the same for someone who is logged in', async () => {
    startServer([publicJob('j1', 'Backend Engineer')], { loggedIn: true })
    renderApp('/jobs')

    expect(await screen.findByRole('article', { name: /backend engineer/i })).toBeInTheDocument()
  })

  it('says so when there are no open jobs at all', async () => {
    startServer([])
    renderApp('/jobs')

    expect(await screen.findByText(/no open jobs right now/i)).toBeInTheDocument()
  })

  it('says so when the server cannot be reached, and lets the visitor try again', async () => {
    const server = startServer([publicJob('j1', 'Backend Engineer')])
    server.state.failNext['GET /api/public/jobs'] = { status: 500 }
    renderApp('/jobs')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByRole('article', { name: /backend engineer/i })).toBeInTheDocument()
  })
})

describe('PublicJobsPage: searching', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('searches by keywords and location when the form is submitted', async () => {
    const { calls } = startServer([
      publicJob('j1', 'Python Developer', { location: 'Oslo' }),
      publicJob('j2', 'Python Tester', { location: 'Lisbon' }),
      publicJob('j3', 'Cook', { location: 'Oslo' }),
    ])
    renderApp('/jobs')
    await screen.findByText(/3 jobs found/i)

    fillIn(/keywords/i, 'python')
    fillIn(/location/i, 'oslo')
    press(/^search$/i)

    expect(await screen.findByText(/1 job found/i)).toBeInTheDocument()
    expect(screen.getByRole('article', { name: /python developer/i })).toBeInTheDocument()
    expect(screen.queryByRole('article', { name: /python tester/i })).not.toBeInTheDocument()
    const last = searches(calls).at(-1)!
    expect(last.get('q')).toBe('python')
    expect(last.get('location')).toBe('oslo')
    expect(last.get('page')).toBe('1')
  })

  it('does not search on every keystroke', async () => {
    const { calls } = startServer([publicJob('j1', 'Python Developer')])
    renderApp('/jobs')
    await screen.findByText(/1 job found/i)
    const before = searches(calls).length

    fillIn(/keywords/i, 'p')
    fillIn(/keywords/i, 'py')
    fillIn(/keywords/i, 'pyt')

    expect(searches(calls)).toHaveLength(before)
  })

  it('leaves out empty or blank search boxes', async () => {
    const { calls } = startServer([publicJob('j1', 'Python Developer')])
    renderApp('/jobs')
    await screen.findByText(/1 job found/i)

    fillIn(/keywords/i, '   ')
    press(/^search$/i)

    await waitFor(() => expect(screen.getByText(/1 job found/i)).toBeInTheDocument())
    const last = searches(calls).at(-1)!
    expect(last.has('q')).toBe(false)
    expect(last.has('location')).toBe(false)
  })

  it('ignores blank keywords and location in the address', async () => {
    const { calls } = startServer([publicJob('j1', 'Python Developer')])
    renderApp('/jobs?q=%20%20&location=%20')

    expect(await screen.findByText(/1 job found/i)).toBeInTheDocument()
    const first = searches(calls)[0]
    expect(first.has('q')).toBe(false)
    expect(first.has('location')).toBe(false)
  })

  it('starts from what the address says, so a search can be shared as a link', async () => {
    const { calls } = startServer([
      publicJob('j1', 'Python Developer', { location: 'Oslo' }),
      publicJob('j2', 'Cook', { location: 'Oslo' }),
    ])
    renderApp('/jobs?q=python&location=oslo')

    expect(await screen.findByText(/1 job found/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/keywords/i)).toHaveValue('python')
    expect(screen.getByLabelText(/location/i)).toHaveValue('oslo')
    expect(searches(calls)[0].get('q')).toBe('python')
  })

  it('says when nothing matches, and offers to clear the search', async () => {
    startServer([publicJob('j1', 'Python Developer')])
    renderApp('/jobs')
    await screen.findByText(/1 job found/i)

    fillIn(/keywords/i, 'astronaut')
    press(/^search$/i)

    expect(await screen.findByText(/no jobs match your search/i)).toBeInTheDocument()
    press(/clear search/i)
    expect(await screen.findByText(/1 job found/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/keywords/i)).toHaveValue('')
  })

  it('limits the keywords to what the server accepts', async () => {
    startServer([])
    renderApp('/jobs')

    expect(await screen.findByLabelText(/keywords/i)).toHaveAttribute('maxlength', '200')
    expect(screen.getByLabelText(/location/i)).toHaveAttribute('maxlength', '200')
  })

  it('shows one company when the address names it, and can show all again', async () => {
    const { calls } = startServer([
      publicJob('j1', 'Acme job'),
      publicJob('j2', 'Globex job', { company_id: 'c-globex', company_name: 'Globex' }),
    ])
    renderApp('/jobs?company_id=c-globex')

    expect(await screen.findByText(/jobs at globex/i)).toBeInTheDocument()
    expect(screen.queryByRole('article', { name: /acme job/i })).not.toBeInTheDocument()
    expect(searches(calls)[0].get('company_id')).toBe('c-globex')

    press(/show all companies/i)

    expect(await screen.findByRole('article', { name: /acme job/i })).toBeInTheDocument()
    expect(searches(calls).at(-1)!.has('company_id')).toBe(false)
  })
})

describe('PublicJobsPage: paging', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('shows one page at a time and keeps the search while moving between pages', async () => {
    const many = Array.from({ length: 45 }, (_, n) =>
      publicJob(`j${n}`, `Python ${String(n).padStart(2, '0')}`),
    )
    const { calls } = startServer(many)
    renderApp('/jobs?q=python')

    expect(await screen.findByText('Python 00')).toBeInTheDocument()
    expect(screen.getByText(/45 jobs found/i)).toBeInTheDocument()
    expect(screen.getByText(/page 1 of 3/i)).toBeInTheDocument()

    press(/next/i)

    expect(await screen.findByText('Python 20')).toBeInTheDocument()
    expect(screen.queryByText('Python 00')).not.toBeInTheDocument()
    const last = searches(calls).at(-1)!
    expect(last.get('page')).toBe('2')
    expect(last.get('q')).toBe('python')
  })

  it('opens at the page the address names', async () => {
    const many = Array.from({ length: 45 }, (_, n) =>
      publicJob(`j${n}`, `Job ${String(n).padStart(2, '0')}`),
    )
    startServer(many)
    renderApp('/jobs?page=3')

    expect(await screen.findByText('Job 40')).toBeInTheDocument()
    expect(screen.getByText(/page 3 of 3/i)).toBeInTheDocument()
  })

  it('treats a nonsense page number in the address as the first page', async () => {
    const { calls } = startServer([publicJob('j1', 'Backend Engineer')])
    renderApp('/jobs?page=abc')

    expect(await screen.findByRole('article', { name: /backend engineer/i })).toBeInTheDocument()
    expect(searches(calls)[0].get('page')).toBe('1')
  })

  it('goes back to the first page when a new search is made', async () => {
    const many = Array.from({ length: 45 }, (_, n) =>
      publicJob(`j${n}`, `Python ${String(n).padStart(2, '0')}`),
    )
    const { calls } = startServer(many)
    renderApp('/jobs?page=3')
    await screen.findByText('Python 40')

    fillIn(/keywords/i, 'python 1')
    press(/^search$/i)

    await waitFor(() => expect(searches(calls).at(-1)!.get('page')).toBe('1'))
  })
})

describe('PublicJobsPage: the way in', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('gives a visitor a "Find jobs" link in the menu', async () => {
    startServer([])
    renderApp('/')

    const link = await screen.findByRole('link', { name: 'Find jobs' })
    expect(link).toHaveAttribute('href', '/jobs')
  })

  it('links to the job search from the home page, also for someone logged in', async () => {
    startServer([], { loggedIn: true })
    renderApp('/')

    const links = await screen.findAllByRole('link', { name: /find a job|browse open jobs/i })
    expect(links.some((link) => link.getAttribute('href') === '/jobs')).toBe(true)
  })

  it('does not hide the search behind the login', async () => {
    startServer([publicJob('j1', 'Backend Engineer')])
    renderApp('/jobs')

    expect(await screen.findByRole('article', { name: /backend engineer/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /log in/i })).not.toBeInTheDocument()
  })
})

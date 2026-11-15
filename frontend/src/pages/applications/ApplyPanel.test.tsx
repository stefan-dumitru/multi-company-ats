import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import {
  adminUser,
  candidateUser,
  recruiterUser,
  sessionFor,
  stubBackend,
  unverifiedCandidate,
} from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

const JOB = {
  id: 'j1',
  title: 'Backend Engineer',
  location: 'Oslo',
  description: 'Build and run our services.',
  department_name: 'Engineering',
  company_id: 'c-acme',
  company_name: 'Acme',
  opened_at: '2026-11-05T12:00:00Z',
}

interface Application {
  id: string
  job_id: string
  job_title: string
  company_name: string
  stage: string
  applied_at: string
  job_is_open: boolean
}

const EXISTING: Application = {
  id: 'a1',
  job_id: 'j1',
  job_title: 'Backend Engineer',
  company_name: 'Acme',
  stage: 'applied',
  applied_at: '2026-11-10T09:00:00Z',
  job_is_open: true,
}

const RESUME = { filename: 'cv.pdf', size_bytes: 1000, uploaded_at: '2026-11-01T09:00:00Z' }

/** The job page's backend. `user: null` is a visitor. */
function startServer(
  options: {
    user?: User | null
    resume?: typeof RESUME | null
    applications?: Application[]
  } = {},
) {
  const state = {
    user: options.user === undefined ? candidateUser : options.user,
    resume: options.resume === undefined ? RESUME : options.resume,
    applications: options.applications ?? [],
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
    if (key === 'GET /api/auth/me') {
      return state.user
        ? { status: 200, body: sessionFor(state.user) }
        : { status: 401, body: { detail: 'Not logged in.' } }
    }
    if (key === 'POST /api/auth/login') {
      state.user = candidateUser
      return { status: 200, body: sessionFor(candidateUser) }
    }
    if (key === 'GET /api/public/jobs/j1') return { status: 200, body: JOB }
    if (key === 'GET /api/profile') {
      return { status: 200, body: { full_name: 'Cara', email: 'c@x.test', resume: state.resume } }
    }
    if (key === 'GET /api/applications') {
      const wanted = url.searchParams.get('job_id')
      const items = state.applications.filter((a) => a.job_id === wanted)
      return { status: 200, body: { items, total: items.length, page: 1, page_size: 20 } }
    }
    if (key === 'POST /api/applications') {
      const created = { ...EXISTING, applied_at: '2026-11-15T10:00:00Z' }
      state.applications = [created]
      return { status: 201, body: created }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

describe('Applying from the job page', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('asks a visitor to log in or register, and brings them back here after logging in', async () => {
    const server = startServer({ user: null })
    renderApp('/jobs/j1')

    await screen.findByRole('heading', { name: 'Backend Engineer' })
    expect(screen.getByText(/log in or register to apply/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /apply/i })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'register' })).toHaveAttribute(
      'href',
      '/register/candidate',
    )

    // The menu has a Log in link too: use the one in the apply message.
    const message = screen.getByText(/log in or register to apply/i).closest('p') as HTMLElement
    fireEvent.click(within(message).getByRole('link', { name: 'Log in' }))
    await screen.findByLabelText(/email/i)
    fillIn(/email/i, 'cara@example.test')
    fillIn(/password/i, 'correct horse battery')
    press(/log in/i)

    // Back on the job, now able to apply.
    expect(await screen.findByRole('button', { name: 'Apply' })).toBeInTheDocument()
    expect(server.calls.some((call) => call.path === '/api/profile')).toBe(true)
  })

  it.each([
    ['an admin', adminUser],
    ['a recruiter', recruiterUser],
  ])('shows %s no apply controls at all', async (_label, user) => {
    const server = startServer({ user })
    renderApp('/jobs/j1')

    await screen.findByRole('heading', { name: 'Backend Engineer' })

    expect(screen.queryByText(/apply/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /log in/i })).not.toBeInTheDocument()
    // Staff are never asked about candidate data.
    expect(server.calls.some((call) => call.path.startsWith('/api/profile'))).toBe(false)
    expect(server.calls.some((call) => call.path.startsWith('/api/applications'))).toBe(false)
  })

  it('tells a candidate who has not verified their email to do that first', async () => {
    const server = startServer({ user: unverifiedCandidate })
    renderApp('/jobs/j1')

    expect(await screen.findByText(/verify your email to apply/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /your profile/i })).toHaveAttribute('href', '/profile')
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
    // An unverified account is refused by the server: do not even ask it.
    expect(server.calls.some((call) => call.path.startsWith('/api/applications'))).toBe(false)
  })

  it('asks a candidate without a resume to add one', async () => {
    startServer({ resume: null })
    renderApp('/jobs/j1')

    expect(await screen.findByText(/add your resume to apply/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /your profile/i })).toHaveAttribute('href', '/profile')
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
  })

  it('applies, then says when', async () => {
    const server = startServer()
    renderApp('/jobs/j1')
    await screen.findByRole('button', { name: 'Apply' })

    press('Apply')

    expect(
      await screen.findByText(`You applied on ${formatDate('2026-11-15T10:00:00Z')}`),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
    expect(
      within(screen.getByRole('article')).getByRole('link', { name: /my applications/i }),
    ).toHaveAttribute('href', '/applications')
    const post = server.calls.find((call) => call.method === 'POST')
    expect(post?.path).toBe('/api/applications')
    expect(post?.body).toEqual({ job_id: 'j1' }) // only the job: who and when come from the server
  })

  it('switches the button off while the request runs, so a second click cannot send another', async () => {
    startServer()
    renderApp('/jobs/j1')
    await screen.findByRole('button', { name: 'Apply' })

    press('Apply')

    await waitFor(() => expect(screen.getByRole('button', { name: /appl/i })).toBeDisabled())
    await screen.findByText(/you applied on/i)
  })

  it('shows the date of an application made earlier, without an Apply button', async () => {
    startServer({ applications: [EXISTING] })
    renderApp('/jobs/j1')

    expect(
      await screen.findByText(`You applied on ${formatDate(EXISTING.applied_at)}`),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
  })

  it('says so when the application was withdrawn, and points to where it can be reactivated', async () => {
    startServer({ applications: [{ ...EXISTING, stage: 'withdrawn' }] })
    renderApp('/jobs/j1')

    expect(await screen.findByText(/you withdrew your application/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
    expect(
      within(screen.getByRole('article')).getByRole('link', { name: /my applications/i }),
    ).toBeInTheDocument()
  })

  it('explains it when the job closed after the page was opened', async () => {
    const server = startServer()
    renderApp('/jobs/j1')
    await screen.findByRole('button', { name: 'Apply' })
    server.state.failNext['POST /api/applications'] = {
      status: 409,
      body: { detail: 'This job is no longer open.', code: 'job_not_open' },
    }

    press('Apply')

    expect(await screen.findByRole('alert')).toHaveTextContent('This job is no longer open.')
    expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled() // they may retry or leave
  })

  it('shows the reason when the resume went missing', async () => {
    const server = startServer()
    renderApp('/jobs/j1')
    await screen.findByRole('button', { name: 'Apply' })
    server.state.failNext['POST /api/applications'] = {
      status: 409,
      body: { detail: 'Add a resume to your profile first.', code: 'resume_required' },
    }

    press('Apply')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Add a resume to your profile first.',
    )
  })

  it('reports a failure to load what the candidate needs, with a way to retry', async () => {
    const server = startServer()
    server.state.failNext['GET /api/profile'] = { status: 500, body: {} }
    renderApp('/jobs/j1')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()

    press(/try again/i)

    expect(await screen.findByRole('button', { name: 'Apply' })).toBeInTheDocument()
  })
})

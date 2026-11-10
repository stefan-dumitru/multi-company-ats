import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { Reply } from '@/test-utils'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

interface Department {
  id: string
  name: string
  is_archived: boolean
}

const ENGINEERING = { id: 'dep-eng', name: 'Engineering', is_archived: false }
const SALES = { id: 'dep-sales', name: 'Sales', is_archived: false }

function startServer(options: { departments?: Department[]; user?: typeof adminUser } = {}) {
  const departments = options.departments ?? [ENGINEERING, SALES]
  const state = { failNext: {} as Record<string, Reply> }

  const backend = stubBackend((call) => {
    const url = new URL(call.path, 'http://app.test')
    const key = `${call.method} ${url.pathname}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /api/auth/me')
      return { status: 200, body: sessionFor(options.user ?? adminUser) }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/departments') {
      return {
        status: 200,
        body: { items: departments, total: departments.length, page: 1, page_size: 100 },
      }
    }
    if (key === 'GET /api/jobs') {
      return { status: 200, body: { items: [], total: 0, page: 1, page_size: 20 } }
    }
    if (key === 'POST /api/jobs') {
      return { status: 201, body: { id: 'j-new' } }
    }
    if (key === 'GET /api/jobs/j-new') {
      return {
        status: 200,
        body: {
          id: 'j-new',
          title: 'Backend Engineer',
          location: 'Oslo or remote',
          description: 'Build and run our services.',
          status: 'draft',
          department: SALES,
          created_at: '2026-11-10T12:00:00Z',
          opened_at: null,
          closed_at: null,
          version: 1,
          needs_reassignment: false,
          recruiters: [],
        },
      }
    }
    if (key === 'GET /api/recruiters') {
      return { status: 200, body: { items: [], total: 0, page: 1, page_size: 100 } }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function fillTheForm() {
  fillIn(/^title$/i, 'Backend Engineer')
  fillIn(/^location$/i, 'Oslo or remote')
  fireEvent.change(screen.getByLabelText(/^department$/i), { target: { value: 'dep-sales' } })
  fillIn(/^description$/i, 'Build and run our services.')
}

describe('NewJobPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('offers only departments that can be used, asking the server for exactly those', async () => {
    const { calls } = startServer()
    renderApp('/manage/jobs/new')

    await screen.findByLabelText(/^title$/i)
    const select = screen.getByLabelText(/^department$/i)
    await waitFor(() => expect(select.querySelectorAll('option').length).toBe(3))
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      'Choose a department',
      'Engineering',
      'Sales',
    ])
    const asked = calls.find((c) => c.path.startsWith('/api/departments'))!
    expect(asked.path).toBe('/api/departments?page_size=100') // no archived ones
  })

  it('creates the job as a draft with the CSRF token and opens its page', async () => {
    const { calls } = startServer()
    renderApp('/manage/jobs/new')
    await screen.findByLabelText(/^title$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())

    fillTheForm()
    press(/create job/i)

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
    expect(screen.getByText('Draft')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.path === '/api/jobs')!
    expect(post.body).toEqual({
      title: 'Backend Engineer',
      location: 'Oslo or remote',
      description: 'Build and run our services.',
      department_id: 'dep-sales',
    })
    expect(post.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('works the same for a recruiter', async () => {
    startServer({ user: recruiterUser })
    renderApp('/manage/jobs/new')
    await screen.findByLabelText(/^title$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())

    fillTheForm()
    press(/create job/i)

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
  })

  it('shows the server message and keeps everything typed when the job is refused', async () => {
    const server = startServer()
    server.state.failNext['POST /api/jobs'] = {
      status: 422,
      body: { detail: 'That department is archived. Choose another.', code: 'department_archived' },
    }
    renderApp('/manage/jobs/new')
    await screen.findByLabelText(/^title$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())
    fillTheForm()

    press(/create job/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/department is archived/i)
    expect(screen.getByLabelText(/^title$/i)).toHaveValue('Backend Engineer')
    expect(screen.getByLabelText(/^description$/i)).toHaveValue('Build and run our services.')
    expect(screen.getByLabelText(/^department$/i)).toHaveValue('dep-sales')
    expect(screen.getByRole('button', { name: /create job/i })).toBeEnabled()
  })

  it('does not send the form twice when it is submitted twice before the screen updates', async () => {
    const { calls } = startServer()
    renderApp('/manage/jobs/new')
    await screen.findByLabelText(/^title$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())
    fillTheForm()

    // Two submits inside one batch: React has not re-rendered (and disabled the button) between
    // them, which is what a fast double click does in a browser.
    const form = screen.getByLabelText(/^title$/i).closest('form')!
    act(() => {
      fireEvent.submit(form)
      fireEvent.submit(form)
    })

    await screen.findByRole('heading', { name: 'Backend Engineer' })
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('explains what to do when the company has no department yet', async () => {
    startServer({ departments: [] })
    renderApp('/manage/jobs/new')

    expect(await screen.findByText(/no departments yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /add a department/i })).toHaveAttribute(
      'href',
      '/departments',
    )
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument()
  })

  it('tells a recruiter to ask an admin, since they cannot add departments', async () => {
    startServer({ departments: [], user: recruiterUser })
    renderApp('/manage/jobs/new')

    expect(await screen.findByText(/ask a company admin/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /add a department/i })).not.toBeInTheDocument()
  })

  it('says so when the departments cannot be loaded, and lets the user try again', async () => {
    const server = startServer()
    server.state.failNext['GET /api/departments'] = { status: 500 }
    renderApp('/manage/jobs/new')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByLabelText(/^title$/i)).toBeInTheDocument()
  })

  it('is not available to an interviewer', async () => {
    const interviewer = { ...recruiterUser, id: 'u-int', role: 'interviewer' as const }
    const { calls } = startServer({ user: interviewer })
    renderApp('/manage/jobs/new')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/departments'))).toBe(false)
  })
})

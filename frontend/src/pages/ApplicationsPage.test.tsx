import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, candidateUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'
import type { MyApplication } from './applications/types'

function application(overrides: Partial<MyApplication> = {}): MyApplication {
  return {
    id: 'a1',
    job_id: 'j1',
    job_title: 'Backend Engineer',
    company_name: 'Acme',
    stage: 'applied',
    applied_at: '2026-11-10T09:00:00Z',
    job_is_open: true,
    ...overrides,
  }
}

function startServer(
  options: { user?: User; applications?: MyApplication[]; pageSize?: number } = {},
) {
  const user = options.user ?? candidateUser
  const state = {
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
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(user) }
    if (key === 'GET /api/applications') {
      const page = Number(url.searchParams.get('page') ?? '1')
      const size = Number(url.searchParams.get('page_size') ?? '20')
      const items = state.applications.slice((page - 1) * size, page * size)
      return {
        status: 200,
        body: { items, total: state.applications.length, page, page_size: size },
      }
    }
    const change = /^POST \/api\/applications\/([^/]+)\/(withdraw|reactivate)$/.exec(key)
    if (change) {
      const found = state.applications.find((a) => a.id === change[1])
      if (!found) return { status: 404, body: { detail: 'Not found.' } }
      found.stage = change[2] === 'withdraw' ? 'withdrawn' : 'applied'
      return { status: 200, body: found }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function card(title: string): HTMLElement {
  const heading = screen.getByRole('heading', { name: title })
  return heading.closest('li') as HTMLElement
}

describe('ApplicationsPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists each application with its company, date and stage', async () => {
    startServer({
      applications: [
        application(),
        application({ id: 'a2', job_id: 'j2', job_title: 'Designer', stage: 'interview' }),
      ],
    })
    renderApp('/applications')

    await screen.findByRole('heading', { name: 'Backend Engineer' })
    const first = within(card('Backend Engineer'))
    expect(first.getByText('Acme')).toBeInTheDocument()
    expect(first.getByText(`Applied ${formatDate('2026-11-10T09:00:00Z')}`)).toBeInTheDocument()
    expect(first.getByText('Applied')).toBeInTheDocument() // the stage badge
    expect(within(card('Designer')).getByText('Interview')).toBeInTheDocument()
  })

  it('links to the job only while it is still open', async () => {
    startServer({
      applications: [
        application(),
        application({ id: 'a2', job_id: 'j2', job_title: 'Old role', job_is_open: false }),
      ],
    })
    renderApp('/applications')

    await screen.findByRole('heading', { name: 'Backend Engineer' })
    expect(within(card('Backend Engineer')).getByRole('link')).toHaveAttribute('href', '/jobs/j1')
    expect(within(card('Old role')).queryByRole('link')).not.toBeInTheDocument()
  })

  it('shows a friendly message and a way to find jobs when there is nothing yet', async () => {
    startServer()
    renderApp('/applications')

    expect(await screen.findByText(/you have not applied to anything yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /find a job/i })).toHaveAttribute('href', '/jobs')
  })

  it('asks before withdrawing, and sends nothing if the candidate changes their mind', async () => {
    const server = startServer({ applications: [application()] })
    renderApp('/applications')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    fireEvent.click(within(card('Backend Engineer')).getByRole('button', { name: 'Withdraw' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
    expect(within(card('Backend Engineer')).getByText('Applied')).toBeInTheDocument()
  })

  it('withdraws once confirmed and shows the new stage from the server', async () => {
    const server = startServer({ applications: [application({ stage: 'interview' })] })
    renderApp('/applications')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    fireEvent.click(within(card('Backend Engineer')).getByRole('button', { name: 'Withdraw' }))
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Withdraw' }))

    expect(await within(card('Backend Engineer')).findByText('Withdrawn')).toBeInTheDocument()
    expect(within(card('Backend Engineer')).queryByRole('button', { name: 'Withdraw' })).toBeNull()
    expect(server.calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([
      '/api/applications/a1/withdraw',
    ])
  })

  it('reactivates a withdrawn application', async () => {
    const server = startServer({ applications: [application({ stage: 'withdrawn' })] })
    renderApp('/applications')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    fireEvent.click(within(card('Backend Engineer')).getByRole('button', { name: 'Reactivate' }))

    expect(await within(card('Backend Engineer')).findByText('Applied')).toBeInTheDocument()
    expect(server.calls.some((call) => call.path === '/api/applications/a1/reactivate')).toBe(true)
  })

  it('cannot reactivate once the job has closed, and says why', async () => {
    startServer({ applications: [application({ stage: 'withdrawn', job_is_open: false })] })
    renderApp('/applications')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    const mine = within(card('Backend Engineer'))
    expect(mine.getByRole('button', { name: 'Reactivate' })).toBeDisabled()
    expect(mine.getByText(/this job is closed/i)).toBeInTheDocument()
  })

  it.each(['hired', 'rejected'] as const)('offers no action on a %s application', async (stage) => {
    startServer({ applications: [application({ stage })] })
    renderApp('/applications')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    expect(within(card('Backend Engineer')).queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows the server’s reason when a change is refused', async () => {
    const server = startServer({ applications: [application()] })
    renderApp('/applications')
    await screen.findByRole('heading', { name: 'Backend Engineer' })
    server.state.failNext['POST /api/applications/a1/withdraw'] = {
      status: 409,
      body: { detail: 'This application has ended.', code: 'application_ended' },
    }

    fireEvent.click(within(card('Backend Engineer')).getByRole('button', { name: 'Withdraw' }))
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Withdraw' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('This application has ended.')
  })

  it('pages through a long list', async () => {
    const many = Array.from({ length: 21 }, (_, index) =>
      application({ id: `a${index}`, job_title: `Job ${index}` }),
    )
    startServer({ applications: many })
    renderApp('/applications')
    await screen.findByRole('heading', { name: 'Job 0' })
    expect(screen.queryByRole('heading', { name: 'Job 20' })).not.toBeInTheDocument()

    press('Next')

    expect(await screen.findByRole('heading', { name: 'Job 20' })).toBeInTheDocument()
  })

  it('reports a failure to load, with a way to try again', async () => {
    const server = startServer({ applications: [application()] })
    server.state.failNext['GET /api/applications'] = { status: 500, body: {} }
    renderApp('/applications')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    press(/try again/i)

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
  })

  it('is not a page for company staff', async () => {
    const server = startServer({ user: adminUser })
    renderApp('/applications')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(server.calls.some((call) => call.path.startsWith('/api/applications'))).toBe(false)
  })
})

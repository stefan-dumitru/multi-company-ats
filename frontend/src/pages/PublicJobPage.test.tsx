import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'

interface PublicJobDetail {
  id: string
  title: string
  location: string
  description: string
  department_name: string
  company_id: string
  company_name: string
  opened_at: string | null
}

const JOB: PublicJobDetail = {
  id: 'j1',
  title: 'Backend Engineer',
  location: 'Oslo',
  description: 'Build and run our services.\n\nYou will work in a small team.',
  department_name: 'Engineering',
  company_id: 'c-acme',
  company_name: 'Acme',
  opened_at: '2026-11-05T12:00:00Z',
}

function startServer(job: PublicJobDetail | null = JOB) {
  const state = { failNext: {} as Record<string, Reply> }

  const backend = stubBackend((call) => {
    const url = new URL(call.path, 'http://app.test')
    const key = `${call.method} ${url.pathname}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /api/auth/me') return { status: 401, body: { detail: 'Not logged in.' } }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (call.method === 'GET' && url.pathname.startsWith('/api/public/jobs/')) {
      if (job && url.pathname === `/api/public/jobs/${job.id}`) return { status: 200, body: job }
      return { status: 404, body: { detail: 'Not found.' } }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

describe('PublicJobPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a job in full to a visitor who is not logged in', async () => {
    startServer()
    renderApp('/jobs/j1')

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByText('Engineering')).toBeInTheDocument()
    expect(screen.getByText('Oslo')).toBeInTheDocument()
    expect(screen.getByText(formatDate('2026-11-05T12:00:00Z'))).toBeInTheDocument()
    expect(screen.getByText(/build and run our services/i)).toBeInTheDocument()
    expect(screen.getByText(/small team/i)).toBeInTheDocument()
  })

  it('links to the other jobs of the same company, and back to the search', async () => {
    startServer()
    renderApp('/jobs/j1')

    expect(await screen.findByRole('link', { name: /more jobs at acme/i })).toHaveAttribute(
      'href',
      '/jobs?company_id=c-acme',
    )
    expect(screen.getByRole('link', { name: /all jobs/i })).toHaveAttribute('href', '/jobs')
  })

  it('shows the text as text, never as HTML', async () => {
    startServer({
      ...JOB,
      title: '<img src=x onerror=alert(1)>',
      description: '<script>alert(1)</script><b>bold</b>',
      company_name: '<i>Co</i>',
    })
    renderApp('/jobs/j1')

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(screen.getByText('<script>alert(1)</script><b>bold</b>')).toBeInTheDocument()
    expect(document.querySelector('main img, main b, main i, main script')).toBeNull()
  })

  it('keeps the paragraphs of the description', async () => {
    startServer()
    renderApp('/jobs/j1')

    const description = await screen.findByText(/build and run our services/i)
    expect(description.className).toMatch(/whitespace-pre-wrap/)
  })

  it('says the job is no longer available when it does not exist or has closed', async () => {
    startServer(null)
    renderApp('/jobs/gone')

    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /see other open jobs/i })).toHaveAttribute(
      'href',
      '/jobs',
    )
  })

  it('says so when the job cannot be loaded, and lets the visitor try again', async () => {
    const server = startServer()
    server.state.failNext['GET /api/public/jobs/j1'] = { status: 500 }
    renderApp('/jobs/j1')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
  })
})

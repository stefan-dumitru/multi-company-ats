import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, recruiterUser, sessionFor, stubFetch, unverifiedAdmin } from '@/test-utils'
import { press, renderApp } from '@/test-render'

describe('HomePage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('welcomes a visitor and points to the two ways in', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/')

    expect(await screen.findByText(/healthy/i)).toBeInTheDocument()
    expect(screen.queryByText(/welcome,/i)).not.toBeInTheDocument()
    const links = screen.getAllByRole('link', { name: /register your company/i })
    expect(links.some((link) => link.getAttribute('href') === '/register')).toBe(true)
  })

  it('greets a logged-in user by name', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(recruiterUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/')

    expect(await screen.findByText('Welcome, Rae Recruiter.')).toBeInTheDocument()
  })

  it('shows the user-chosen name as text, never as HTML', async () => {
    const sneaky = { ...recruiterUser, full_name: '<b>bold</b>' }
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(sneaky) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/')

    expect(await screen.findByText('Welcome, <b>bold</b>.')).toBeInTheDocument()
    expect(document.querySelector('main b')).toBeNull()
  })

  it('points an admin to the page where the team is managed', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/')

    await screen.findByText(/welcome, ada admin/i)
    const links = screen.getAllByRole('link', { name: /manage users|invite your team/i })
    expect(links.some((link) => link.getAttribute('href') === '/users')).toBe(true)
  })

  it('tells an unverified user to verify, and lets them ask for a new link', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) },
      'GET /health': { status: 200, body: { status: 'ok' } },
      'POST /api/auth/resend-verification': { status: 204 },
    })
    renderApp('/')

    expect(await screen.findByText(/your email address is not verified yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /manage users/i })).not.toBeInTheDocument()

    press(/send me a new link/i)

    expect(await screen.findByText(/we sent a new link to ada@acme\.test/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/auth/resend-verification')).toBe(true)
  })

  it('shows no verification notice to a verified user', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/')

    expect(await screen.findByRole('link', { name: /manage users/i })).toBeInTheDocument()
    expect(screen.queryByText(/not verified yet/i)).not.toBeInTheDocument()
  })
})

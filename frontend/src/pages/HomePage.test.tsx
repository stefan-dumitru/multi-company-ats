import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { recruiterUser, sessionFor, stubFetch } from '@/test-utils'
import { renderApp } from '@/test-render'

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
})

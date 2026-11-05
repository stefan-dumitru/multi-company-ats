import { fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

describe('who can open the Users page', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends a visitor to log in first, then brings them to the page they wanted', async () => {
    let loggedIn = false
    stubBackend((call) => {
      const key = `${call.method} ${call.path}`
      if (key === 'GET /api/auth/me') {
        return loggedIn ? { status: 200, body: sessionFor(adminUser) } : { status: 401 }
      }
      if (key === 'POST /api/auth/login') {
        loggedIn = true
        return { status: 200, body: sessionFor(adminUser) }
      }
      if (key === 'GET /api/users') return { status: 200, body: [] }
      if (key === 'GET /api/invitations') return { status: 200, body: [] }
      throw new Error(`Unplanned request: ${key}`)
    })
    renderApp('/users')

    await screen.findByLabelText(/email/i)
    fillIn(/email/i, 'ada@acme.test')
    fillIn(/password/i, 'correct horse battery')
    press(/^log in$/i)

    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument()
  })

  it('shows "not found" to a recruiter, and never even asks the server for the list', async () => {
    const { calls } = stubBackend((call) => {
      if (call.path === '/api/auth/me') return { status: 200, body: sessionFor(recruiterUser) }
      throw new Error(`Unplanned request: ${call.method} ${call.path}`)
    })
    renderApp('/users')

    expect(await screen.findByRole('heading', { name: /page not found/i })).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/users')).toBe(false)
  })

  it('gives an admin a Users link in the menu that opens the page', async () => {
    stubBackend((call) => {
      const key = `${call.method} ${call.path}`
      if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(adminUser) }
      if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
      if (key === 'GET /api/users') return { status: 200, body: [] }
      if (key === 'GET /api/invitations') return { status: 200, body: [] }
      throw new Error(`Unplanned request: ${key}`)
    })
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: 'Users' }))

    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument()
  })

  it('does not show a recruiter any Users link', async () => {
    stubBackend((call) => {
      if (call.path === '/api/auth/me') return { status: 200, body: sessionFor(recruiterUser) }
      if (call.path === '/health') return { status: 200, body: { status: 'ok' } }
      throw new Error(`Unplanned request: ${call.method} ${call.path}`)
    })
    renderApp('/')

    await screen.findByText(/welcome, rae recruiter/i)
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
  })
})

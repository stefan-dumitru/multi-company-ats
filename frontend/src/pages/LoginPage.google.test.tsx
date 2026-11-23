import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { Reply } from '@/test-utils'
import { stubBackend } from '@/test-utils'
import App from '@/App'
import { AuthProvider } from '@/auth/AuthContext'
import { renderApp } from '@/test-render'

const START = '/api/auth/google/start'

/** A logged-out visitor, and a server that does or does not have Google set up. */
function startServer(options: { enabled?: boolean; configReply?: Reply } = {}) {
  const enabled = options.enabled ?? true
  return stubBackend((call) => {
    const key = `${call.method} ${new URL(call.path, 'http://app.test').pathname}`
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/auth/me') return { status: 401, body: {} }
    if (key === 'GET /api/auth/google/config') {
      return options.configReply ?? { status: 200, body: { enabled } }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })
}

/** Shows the address the app is at, so a test can see what the page did to it. */
function AddressProbe() {
  const location = useLocation()
  return <output aria-label="address">{`${location.pathname}${location.search}`}</output>
}

describe('Continue with Google', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  // ---- the button -------------------------------------------------------------------------

  it.each([
    ['the login page', '/login'],
    ['the candidate sign-up page', '/register/candidate'],
  ])('is offered on %s when the server has Google set up', async (_where, path) => {
    startServer()
    renderApp(path)

    const link = await screen.findByRole('link', { name: 'Continue with Google' })
    // A plain link, so the browser itself goes to our server and on to Google.
    expect(link).toHaveAttribute('href', START)
    expect(link).not.toHaveAttribute('target') // the way back must land in this same tab
  })

  it.each([
    ['the login page', '/login', /log in/i],
    ['the candidate sign-up page', '/register/candidate', /create account/i],
  ])('is not offered on %s when the server has no Google', async (_where, path, submit) => {
    const server = startServer({ enabled: false })
    renderApp(path)

    await screen.findByRole('button', { name: submit })
    await waitFor(() =>
      expect(server.calls.some((call) => call.path === '/api/auth/google/config')).toBe(true),
    )
    expect(screen.queryByRole('link', { name: /google/i })).not.toBeInTheDocument()
  })

  it('does not get in the way of a password login when the setting cannot be loaded', async () => {
    startServer({ configReply: { status: 500, body: {} } })
    renderApp('/login')

    expect(await screen.findByRole('button', { name: /log in/i })).toBeEnabled()
    await waitFor(() => expect(screen.queryByText(/loading/i)).not.toBeInTheDocument())
    expect(screen.queryByRole('link', { name: /google/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  // ---- the way back with a problem --------------------------------------------------------

  it.each([
    ['access_denied', /did not allow access/],
    ['bad_state', /expired or was not started here/],
    ['missing_code', /did not send/],
    ['google_unavailable', /could not be reached/],
    ['google_refused', /did not accept/],
    ['google_error', /reported a problem/],
    ['not_configured', /isn.t set up/],
    ['email_not_verified', /has not verified that email/],
    ['account_unverified', /Log in with your password first/],
    ['account_unavailable', /cannot sign in/],
    ['try_again', /try again/],
  ])('explains the way back error %s in plain words', async (code, words) => {
    startServer()
    renderApp(`/login?google_error=${code}`)

    expect(await screen.findByRole('alert')).toHaveTextContent(words)
  })

  it('gives a generic message for a code it does not know, never echoing the address', async () => {
    startServer()
    renderApp('/login?google_error=hello-world')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Signing in with Google did not work.')
    expect(alert).not.toHaveTextContent('hello-world')
  })

  it('shows nothing about Google on an ordinary visit', async () => {
    startServer()
    renderApp('/login')

    await screen.findByRole('link', { name: 'Continue with Google' })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('removes the note from the address so a refresh does not repeat it, and keeps showing it', async () => {
    startServer()
    render(
      <MemoryRouter initialEntries={['/login?google_error=access_denied']}>
        <AuthProvider>
          <App />
          <AddressProbe />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('did not allow access')
    await waitFor(() => expect(screen.getByLabelText('address')).toHaveTextContent(/^\/login$/))
    expect(screen.getByRole('alert')).toHaveTextContent('did not allow access')
  })

  it('still lets the person log in with a password after a Google problem', async () => {
    startServer()
    renderApp('/login?google_error=account_unverified')

    await screen.findByRole('alert')
    expect(screen.getByLabelText(/email/i)).toBeEnabled()
    expect(screen.getByRole('button', { name: /log in/i })).toBeEnabled()
  })
})

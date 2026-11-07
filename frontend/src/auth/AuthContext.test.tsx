import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, sessionFor, stubFetch, unverifiedAdmin } from '@/test-utils'
import { AuthProvider, useAuth } from './AuthContext'

/** Shows whatever the auth context says, and has a button for each thing a page can do. */
function Probe() {
  const { state, login, logout, startSession, refreshUser } = useAuth()
  const [problem, setProblem] = useState('')

  return (
    <div>
      <p>status: {state.status}</p>
      {state.status === 'authenticated' && <p>user: {state.user.email}</p>}
      {state.status === 'anonymous' && state.notice && <p>notice: {state.notice}</p>}
      {problem && <p role="alert">{problem}</p>}
      <button onClick={() => login('ada@acme.test', 'pw').catch((e) => setProblem(e.message))}>
        log in
      </button>
      <button onClick={() => logout().catch((e) => setProblem(e.message))}>log out</button>
      <button onClick={() => startSession(sessionFor(adminUser, 'from-signup'))}>
        start session
      </button>
      <button onClick={() => api('/api/users').catch(() => undefined)}>ask for users</button>
      <button onClick={() => refreshUser().catch((e) => setProblem(e.message))}>refresh</button>
      {state.status === 'authenticated' && (
        <p>verified: {state.user.email_verified_at === null ? 'no' : 'yes'}</p>
      )}
    </div>
  )
}

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is loading until the server says who is logged in', () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))

    renderProbe()

    expect(screen.getByText('status: loading')).toBeInTheDocument()
  })

  it('is authenticated when the browser already has a valid session', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) } })

    renderProbe()

    expect(await screen.findByText('user: ada@acme.test')).toBeInTheDocument()
  })

  it('is anonymous, with no scary message, when nobody is logged in', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401, body: { detail: 'Not logged in.' } } })

    renderProbe()

    expect(await screen.findByText('status: anonymous')).toBeInTheDocument()
    expect(screen.queryByText(/notice/)).not.toBeInTheDocument()
  })

  it('is anonymous when the server cannot be reached at startup', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    renderProbe()

    expect(await screen.findByText('status: anonymous')).toBeInTheDocument()
  })

  it('logs in, remembers the user, and uses the new CSRF token from then on', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': { status: 200, body: sessionFor(adminUser, 'token-from-login') },
      'POST /api/auth/logout': { status: 204 },
    })
    renderProbe()
    await screen.findByText('status: anonymous')

    fireEvent.click(screen.getByRole('button', { name: 'log in' }))
    expect(await screen.findByText('user: ada@acme.test')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/login')?.body).toEqual({
      email: 'ada@acme.test',
      password: 'pw',
    })

    fireEvent.click(screen.getByRole('button', { name: 'log out' }))
    await screen.findByText('status: anonymous')
    const logout = calls.find((c) => c.path === '/api/auth/logout')
    expect(logout?.headers['X-CSRF-Token']).toBe('token-from-login')
  })

  it('stays anonymous after a wrong password, without claiming the session expired', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': { status: 401, body: { detail: 'Invalid email or password.' } },
    })
    renderProbe()
    await screen.findByText('status: anonymous')

    fireEvent.click(screen.getByRole('button', { name: 'log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
    expect(screen.getByText('status: anonymous')).toBeInTheDocument()
    expect(screen.queryByText(/expired/i)).not.toBeInTheDocument()
  })

  it('logs out: back to anonymous, and the CSRF token is forgotten', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser, 'abc') },
      'POST /api/auth/logout': { status: 204 },
      'GET /api/users': { status: 401 },
    })
    renderProbe()
    await screen.findByText('user: ada@acme.test')

    fireEvent.click(screen.getByRole('button', { name: 'log out' }))

    expect(await screen.findByText('status: anonymous')).toBeInTheDocument()
    expect(screen.queryByText(/notice/)).not.toBeInTheDocument()
    await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
    expect(calls.at(-1)?.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('stays logged in, and says so, if the logout request cannot be sent', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) } })
    renderProbe()
    await screen.findByText('user: ada@acme.test')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    fireEvent.click(screen.getByRole('button', { name: 'log out' }))

    // The session still exists on the server, so pretending to be logged out would be a lie.
    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the server/i)
    expect(screen.getByText('user: ada@acme.test')).toBeInTheDocument()
  })

  it('drops to anonymous with a notice when the session expires mid-use', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'GET /api/users': { status: 401, body: { detail: 'Not logged in.' } },
    })
    renderProbe()
    await screen.findByText('user: ada@acme.test')

    fireEvent.click(screen.getByRole('button', { name: 'ask for users' }))

    expect(
      await screen.findByText('notice: Your session has expired. Please log in again.'),
    ).toBeInTheDocument()
  })

  it('lets signup and invitation pages start a session from the server answer', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/logout': { status: 204 },
    })
    renderProbe()
    await screen.findByText('status: anonymous')

    fireEvent.click(screen.getByRole('button', { name: 'start session' }))
    expect(await screen.findByText('user: ada@acme.test')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'log out' }))
    await waitFor(() => expect(calls.at(-1)?.path).toBe('/api/auth/logout'))
    expect(calls.at(-1)?.headers['X-CSRF-Token']).toBe('from-signup')
  })

  it('refuses to be used outside the provider, instead of failing in confusing ways', () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    expect(() => render(<Probe />)).toThrow(/AuthProvider/)

    quiet.mockRestore()
  })
  it('re-reads the user when asked, so a change made elsewhere shows up', async () => {
    let verified = false
    stubFetch({
      'GET /api/auth/me': () => ({
        status: 200,
        body: sessionFor(verified ? adminUser : unverifiedAdmin),
      }),
    })
    renderProbe()
    expect(await screen.findByText('verified: no')).toBeInTheDocument()

    verified = true
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))

    expect(await screen.findByText('verified: yes')).toBeInTheDocument()
  })

  it('keeps the current user and reports the problem when a refresh fails', async () => {
    let failing = false
    stubFetch({
      'GET /api/auth/me': () =>
        failing ? { status: 500 } : { status: 200, body: sessionFor(unverifiedAdmin) },
    })
    renderProbe()
    await screen.findByText('verified: no')

    failing = true
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('verified: no')).toBeInTheDocument()
  })
})

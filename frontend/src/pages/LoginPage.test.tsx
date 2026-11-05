import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { AuthProvider } from '@/auth/AuthContext'
import { RequireAuth } from '@/auth/guards'
import { adminUser, sessionFor, stubFetch } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'
import LoginPage from './LoginPage'

describe('LoginPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('logs in with the typed email and password and lands on the home page', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': { status: 200, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/login')
    await screen.findByLabelText(/email/i)

    fillIn(/email/i, 'ada@acme.test')
    fillIn(/password/i, 'correct horse battery')
    press(/log in/i)

    expect(await screen.findByText(/welcome, ada admin/i)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/login')?.body).toEqual({
      email: 'ada@acme.test',
      password: 'correct horse battery',
    })
  })

  it('has labelled fields that password managers and browsers recognise', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/login')

    expect(await screen.findByLabelText(/email/i)).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('autocomplete', 'current-password')
  })

  it('shows the server message for a wrong password and clears only the password', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': { status: 401, body: { detail: 'Invalid email or password.' } },
    })
    renderApp('/login')
    await screen.findByLabelText(/email/i)
    fillIn(/email/i, 'ada@acme.test')
    fillIn(/password/i, 'not the password')

    press(/log in/i)

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
    expect(screen.getByLabelText(/email/i)).toHaveValue('ada@acme.test')
    expect(screen.getByLabelText(/password/i)).toHaveValue('')
  })

  it('tells a locked-out user to wait', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': {
        status: 429,
        body: { detail: 'Too many failed attempts. Try again later.' },
      },
    })
    renderApp('/login')
    await screen.findByLabelText(/email/i)
    fillIn(/email/i, 'ada@acme.test')
    fillIn(/password/i, 'whatever password')

    press(/log in/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/too many failed attempts/i)
  })

  it('says so when the server cannot be reached', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/login')
    await screen.findByLabelText(/email/i)
    fillIn(/email/i, 'ada@acme.test')
    fillIn(/password/i, 'whatever password')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    press(/log in/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the server/i)
  })

  it('cannot be submitted twice while the first attempt is still running', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/login')
    await screen.findByLabelText(/email/i)
    fillIn(/email/i, 'ada@acme.test')
    fillIn(/password/i, 'whatever password')
    const slow = vi.fn().mockReturnValue(new Promise(() => {}))
    vi.stubGlobal('fetch', slow)

    press(/log in/i)
    fireEvent.click(screen.getByRole('button', { name: /logging in/i }))

    expect(screen.getByRole('button', { name: /logging in/i })).toBeDisabled()
    expect(slow).toHaveBeenCalledTimes(1)
  })

  it('links to company registration', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/login')

    await screen.findByLabelText(/email/i)
    const page = within(screen.getByRole('main'))

    expect(page.getByRole('link', { name: /register your company/i })).toHaveAttribute(
      'href',
      '/register',
    )
  })

  it('sends someone who is already logged in straight home', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/login')

    expect(await screen.findByText(/welcome, ada admin/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  })
})

describe('LoginPage: where to go afterwards', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderLogin(from: string | undefined) {
    return render(
      <MemoryRouter initialEntries={[{ pathname: '/login', state: from ? { from } : undefined }]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<p>home page</p>} />
            <Route path="/users" element={<p>users page</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
  }

  function logInQuickly() {
    fillIn(/email/i, 'ada@acme.test')
    fillIn(/password/i, 'correct horse battery')
    press(/log in/i)
  }

  const loginRoutes = {
    'GET /api/auth/me': { status: 401 },
    'POST /api/auth/login': { status: 200, body: sessionFor(adminUser) },
  }

  it('returns to the page the visitor was trying to open', async () => {
    stubFetch(loginRoutes)
    renderLogin('/users')
    await screen.findByLabelText(/email/i)

    logInQuickly()

    expect(await screen.findByText('users page')).toBeInTheDocument()
  })

  it('goes home when there is nowhere to return to', async () => {
    stubFetch(loginRoutes)
    renderLogin(undefined)
    await screen.findByLabelText(/email/i)

    logInQuickly()

    expect(await screen.findByText('home page')).toBeInTheDocument()
  })

  it.each(['//evil.example/phish', 'https://evil.example', 'javascript:alert(1)'])(
    'never redirects to a place outside the app (%s)',
    async (from) => {
      stubFetch(loginRoutes)
      renderLogin(from)
      await screen.findByLabelText(/email/i)

      logInQuickly()

      expect(await screen.findByText('home page')).toBeInTheDocument()
    },
  )
})

describe('LoginPage: when a session ends', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** A protected page with a button that asks the server something, as real pages will. */
  function SecretPage() {
    const [answer, setAnswer] = useState('')
    return (
      <div>
        <p>secret page</p>
        <button onClick={() => api('/api/ping').catch((e) => setAnswer(e.message))}>ask</button>
        <p>{answer}</p>
      </div>
    )
  }

  it('explains why the user was sent back to log in', async () => {
    setCsrfToken(null)
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'GET /api/ping': { status: 401, body: { detail: 'Not logged in.' } },
    })
    render(
      <MemoryRouter initialEntries={['/secret']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route path="/secret" element={<SecretPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await screen.findByText('secret page')

    press('ask')

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Your session has expired. Please log in again.',
    )
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
  })
})

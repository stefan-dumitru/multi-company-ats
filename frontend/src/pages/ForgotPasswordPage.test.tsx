import { fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { stubFetch } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

const SERVER_ANSWER = {
  detail: 'If an account exists for that address, we have sent a link to reset the password.',
}

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is reachable from the login page', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/login')

    const link = await screen.findByRole('link', { name: /forgot your password/i })

    expect(link).toHaveAttribute('href', '/forgot-password')
  })

  it('sends only the typed email and shows the same neutral answer as the server', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/forgot-password': { status: 202, body: SERVER_ANSWER },
    })
    renderApp('/forgot-password')
    await screen.findByLabelText(/email/i)

    fillIn(/email/i, 'ada@acme.test')
    press(/send reset link/i)

    expect(await screen.findByText(/if an account exists for that address/i)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/forgot-password')?.body).toEqual({
      email: 'ada@acme.test',
    })
  })

  it('never says whether the address has an account', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/forgot-password': { status: 202, body: SERVER_ANSWER },
    })
    renderApp('/forgot-password')
    await screen.findByLabelText(/email/i)

    fillIn(/email/i, 'nobody@acme.test')
    press(/send reset link/i)
    await screen.findByText(/if an account exists/i)

    expect(document.body).not.toHaveTextContent(/no account|not found|does not exist|unknown/i)
  })

  it('shows a validation message from the server for a malformed address', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/forgot-password': { status: 422, body: { detail: [{ msg: 'bad' }] } },
    })
    renderApp('/forgot-password')
    await screen.findByLabelText(/email/i)

    // Accepted by the browser's own check, refused by the server's stricter one.
    fillIn(/email/i, 'ada@localhost')
    press(/send reset link/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/not valid/i)
  })

  it('shows a plain error when the server cannot be reached, and lets the user try again', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/forgot-password': { status: 500 },
    })
    renderApp('/forgot-password')
    await screen.findByLabelText(/email/i)

    fillIn(/email/i, 'ada@acme.test')
    press(/send reset link/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    expect(screen.getByRole('button', { name: /send reset link/i })).toBeEnabled()
  })

  it('blocks a second click while the first request is running', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/forgot-password': { status: 202, body: SERVER_ANSWER },
    })
    renderApp('/forgot-password')
    await screen.findByLabelText(/email/i)
    fillIn(/email/i, 'ada@acme.test')

    const button = screen.getByRole('button', { name: /send reset link/i })
    fireEvent.click(button)
    fireEvent.click(button)
    await screen.findByText(/if an account exists/i)

    expect(calls.filter((c) => c.path === '/api/auth/forgot-password')).toHaveLength(1)
  })
})

import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { sessionFor, stubFetch, unverifiedAdmin } from '@/test-utils'
import { press, renderApp } from '@/test-render'

describe('the "verify your email" screen', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('replaces the app for an unverified user and never loads the page behind it', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) },
    })

    renderApp('/users')

    expect(await screen.findByText('Verify your email')).toBeInTheDocument()
    expect(screen.getByText(/ada@acme\.test/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /^users$/i })).not.toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/users')).toBe(false)
  })

  it('lets the user log out from there', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) } })

    renderApp('/users')
    await screen.findByText('Verify your email')

    expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument()
  })

  it('sends a new link and confirms where it went', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) },
      'POST /api/auth/resend-verification': { status: 204 },
    })
    renderApp('/users')
    await screen.findByText('Verify your email')

    press(/send me a new link/i)

    expect(await screen.findByText(/we sent a new link to ada@acme\.test/i)).toBeInTheDocument()
    const resend = calls.find((c) => c.path === '/api/auth/resend-verification')
    expect(resend?.method).toBe('POST')
    expect(resend?.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('shows the server message when too many links were asked for', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) },
      'POST /api/auth/resend-verification': {
        status: 429,
        body: { detail: 'Too many verification emails requested. Please try again in an hour.' },
      },
    })
    renderApp('/users')
    await screen.findByText('Verify your email')

    press(/send me a new link/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/try again in an hour/i)
  })

  it('shows a plain error when the server is unreachable, and lets the user try again', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) },
      'POST /api/auth/resend-verification': { status: 500 },
    })
    renderApp('/users')
    await screen.findByText('Verify your email')

    press(/send me a new link/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    expect(screen.getByRole('button', { name: /send me a new link/i })).toBeEnabled()
  })
})

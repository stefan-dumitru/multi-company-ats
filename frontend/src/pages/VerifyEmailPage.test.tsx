import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, sessionFor, stubFetch, unverifiedAdmin } from '@/test-utils'
import { press, renderApp } from '@/test-render'

// An invented value, used only to check that the page never prints what is in the link.
const LINK_CODE = 'verification-link-for-tests'
const INVALID = 'This verification link is invalid or has expired.'

describe('VerifyEmailPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses the link once and tells a visitor their email is verified', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/verify-email': { status: 204 },
    })

    renderApp(`/verify-email?token=${LINK_CODE}`)

    expect(await screen.findByText(/your email address is verified/i)).toBeInTheDocument()
    // The page's own link, not the "Log in" in the header.
    expect(
      within(screen.getByRole('main')).getByRole('link', { name: /log in/i }),
    ).toBeInTheDocument()
    const verifyCalls = calls.filter((c) => c.path === '/api/auth/verify-email')
    expect(verifyCalls).toHaveLength(1) // a link works once: asking twice would show a false error
    expect(verifyCalls[0].body).toEqual({ token: LINK_CODE })
  })

  it('does not print the secret token on the page', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/verify-email': { status: 204 },
    })

    renderApp(`/verify-email?token=${LINK_CODE}`)
    await screen.findByText(/your email address is verified/i)

    expect(document.body).not.toHaveTextContent(LINK_CODE)
  })

  it('shows the server message for a bad link and tells a visitor how to get a new one', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/verify-email': { status: 400, body: { detail: INVALID } },
    })

    renderApp(`/verify-email?token=${LINK_CODE}`)

    expect(await screen.findByRole('alert')).toHaveTextContent(INVALID)
    expect(screen.getByRole('main')).toHaveTextContent(/log in to get a new link/i)
  })

  it('explains an address with no link in it, without calling the server', async () => {
    const { calls } = stubFetch({ 'GET /api/auth/me': { status: 401 } })

    renderApp('/verify-email')

    expect(await screen.findByRole('alert')).toHaveTextContent(/incomplete/i)
    expect(calls.some((c) => c.path === '/api/auth/verify-email')).toBe(false)
  })

  it('refreshes a logged-in user, who is then let into the app', async () => {
    let verified = false
    const { calls } = stubFetch({
      'GET /api/auth/me': () => ({
        status: 200,
        body: sessionFor(verified ? adminUser : unverifiedAdmin),
      }),
      'POST /api/auth/verify-email': () => {
        verified = true
        return { status: 204 }
      },
    })

    renderApp(`/verify-email?token=${LINK_CODE}`)

    expect(await screen.findByText(/your email address is verified/i)).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /continue/i })).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/auth/me').length).toBeGreaterThanOrEqual(2)
  })

  it('offers a new link to a logged-in user whose link did not work', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) },
      'POST /api/auth/verify-email': { status: 400, body: { detail: INVALID } },
      'POST /api/auth/resend-verification': { status: 204 },
    })

    renderApp(`/verify-email?token=${LINK_CODE}`)
    await screen.findByRole('alert')
    press(/send me a new link/i)

    expect(await screen.findByText(/we sent a new link to ada@acme\.test/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/auth/resend-verification')).toBe(true)
  })

  it('says verified for someone already verified whose link was used before', async () => {
    // Opening the same link twice (or refreshing the page) fails the second time. For someone who
    // is verified, "invalid link" would be a false alarm.
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'POST /api/auth/verify-email': { status: 400, body: { detail: INVALID } },
    })

    renderApp(`/verify-email?token=${LINK_CODE}`)

    expect(await screen.findByText(/your email address is verified/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

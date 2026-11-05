import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, recruiterUser, sessionFor, stubFetch } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

const SECRET_TOKEN = 'tok-9f8e7d6c5b4a'

describe('AcceptInvitationPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('creates the account from the link, logs the person in and shows the home page', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/invitations/accept': { status: 201, body: sessionFor(recruiterUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp(`/accept-invitation?token=${SECRET_TOKEN}`)
    await screen.findByLabelText(/your name/i)

    fillIn(/your name/i, 'Rae Recruiter')
    fillIn(/password/i, 'correct horse battery')
    press(/join/i)

    expect(await screen.findByText(/welcome, rae recruiter/i)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/invitations/accept')?.body).toEqual({
      token: SECRET_TOKEN,
      full_name: 'Rae Recruiter',
      password: 'correct horse battery',
    })
  })

  it('never asks for, or sends, a role or company: those come from the invitation', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/invitations/accept': { status: 201, body: sessionFor(recruiterUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp(`/accept-invitation?token=${SECRET_TOKEN}`)
    await screen.findByLabelText(/your name/i)

    fillIn(/your name/i, 'Rae Recruiter')
    fillIn(/password/i, 'correct horse battery')
    press(/join/i)
    await screen.findByText(/welcome/i)

    const body = calls.find((c) => c.path === '/api/invitations/accept')?.body as Record<
      string,
      unknown
    >
    expect(Object.keys(body).sort()).toEqual(['full_name', 'password', 'token'])
    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument()
  })

  it('does not print the secret token on the page', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp(`/accept-invitation?token=${SECRET_TOKEN}`)

    await screen.findByLabelText(/your name/i)

    expect(document.body).not.toHaveTextContent(SECRET_TOKEN)
  })

  it('explains a link with no token instead of showing a form that cannot work', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/accept-invitation')

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid or incomplete/i)
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    expect(within(screen.getByRole('main')).getByRole('link', { name: /log in/i })).toHaveAttribute(
      'href',
      '/login',
    )
  })

  it('shows the server answer for a used, expired or revoked link', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/invitations/accept': {
        status: 400,
        body: { detail: 'This invitation link is invalid or has expired.' },
      },
    })
    renderApp(`/accept-invitation?token=${SECRET_TOKEN}`)
    await screen.findByLabelText(/your name/i)
    fillIn(/your name/i, 'Rae Recruiter')
    fillIn(/password/i, 'correct horse battery')

    press(/join/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid or has expired/i)
  })

  it('keeps the name and shows the rule when the password is too weak', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/invitations/accept': {
        status: 422,
        body: { detail: 'Password must be at least 12 characters long.' },
      },
    })
    renderApp(`/accept-invitation?token=${SECRET_TOKEN}`)
    await screen.findByLabelText(/your name/i)
    fillIn(/your name/i, 'Rae Recruiter')
    fillIn(/password/i, 'short')

    press(/join/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least 12 characters/i)
    expect(screen.getByLabelText(/your name/i)).toHaveValue('Rae Recruiter')
    expect(screen.getByLabelText(/password/i)).toHaveValue('')
  })

  it('still works for someone who is logged in as somebody else', async () => {
    // An admin opening a colleague's link on a shared computer must not be bounced home.
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'POST /api/invitations/accept': { status: 201, body: sessionFor(recruiterUser, 'new-token') },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp(`/accept-invitation?token=${SECRET_TOKEN}`)

    await screen.findByLabelText(/your name/i)
    fillIn(/your name/i, 'Rae Recruiter')
    fillIn(/password/i, 'correct horse battery')
    press(/join/i)

    expect(await screen.findByText(/welcome, rae recruiter/i)).toBeInTheDocument()
  })
})

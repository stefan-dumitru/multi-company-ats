import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { stubFetch } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

// An invented value, used only to check that the page never prints what is in the link.
const LINK_CODE = 'reset-link-for-tests'
const INVALID = 'This password reset link is invalid or has expired.'
const NEW_PASSWORD = 'a brand new passphrase'

describe('ResetPasswordPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the link and the new password, then offers to log in', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/reset-password': { status: 204 },
    })
    renderApp(`/reset-password?token=${LINK_CODE}`)
    await screen.findByLabelText(/new password/i)

    fillIn(/new password/i, NEW_PASSWORD)
    press(/set new password/i)

    expect(await screen.findByText(/your password was changed/i)).toBeInTheDocument()
    expect(
      within(screen.getByRole('main')).getByRole('link', { name: /log in/i }),
    ).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/reset-password')?.body).toEqual({
      token: LINK_CODE,
      password: NEW_PASSWORD,
    })
  })

  it('has a password field that password managers recognise as a new password', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp(`/reset-password?token=${LINK_CODE}`)

    const field = await screen.findByLabelText(/new password/i)

    expect(field).toHaveAttribute('type', 'password')
    expect(field).toHaveAttribute('autocomplete', 'new-password')
  })

  it('does not print the secret token on the page', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp(`/reset-password?token=${LINK_CODE}`)

    await screen.findByLabelText(/new password/i)

    expect(document.body).not.toHaveTextContent(LINK_CODE)
  })

  it('shows the server message for a weak password and keeps the form for another try', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/reset-password': {
        status: 422,
        body: { detail: 'Password must be at least 12 characters long.' },
      },
    })
    renderApp(`/reset-password?token=${LINK_CODE}`)
    await screen.findByLabelText(/new password/i)

    fillIn(/new password/i, 'short')
    press(/set new password/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least 12 characters/i)
    expect(screen.getByLabelText(/new password/i)).toHaveValue('') // not left sitting in the field
    expect(screen.getByRole('button', { name: /set new password/i })).toBeEnabled()
  })

  it('explains a bad or used link and points to asking for a new one', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/reset-password': { status: 400, body: { detail: INVALID } },
    })
    renderApp(`/reset-password?token=${LINK_CODE}`)
    await screen.findByLabelText(/new password/i)

    fillIn(/new password/i, NEW_PASSWORD)
    press(/set new password/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(INVALID)
    const link = within(screen.getByRole('main')).getByRole('link', {
      name: /ask for a new link/i,
    })
    expect(link).toHaveAttribute('href', '/forgot-password')
  })

  it('explains an address with no link in it, without showing a form', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/reset-password')

    expect(await screen.findByRole('alert')).toHaveTextContent(/incomplete/i)
    expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument()
  })

  it('blocks a second click while the first request is running', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/reset-password': { status: 204 },
    })
    renderApp(`/reset-password?token=${LINK_CODE}`)
    await screen.findByLabelText(/new password/i)
    fillIn(/new password/i, NEW_PASSWORD)

    const button = screen.getByRole('button', { name: /set new password/i })
    fireEvent.click(button)
    fireEvent.click(button)
    await screen.findByText(/your password was changed/i)

    expect(calls.filter((c) => c.path === '/api/auth/reset-password')).toHaveLength(1)
  })
})

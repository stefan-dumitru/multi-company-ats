import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, sessionFor, stubFetch } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

function fillTheForm() {
  fillIn(/company name/i, 'Acme Corp')
  fillIn(/your name/i, 'Ada Admin')
  fillIn(/email/i, 'ada@acme.test')
  fillIn(/password/i, 'correct horse battery')
}

describe('RegisterCompanyPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('registers the company, logs the new admin in and shows the home page', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/companies': { status: 201, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/register')
    await screen.findByLabelText(/company name/i)

    fillTheForm()
    press(/register/i)

    expect(await screen.findByText(/welcome, ada admin/i)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/companies')?.body).toEqual({
      company_name: 'Acme Corp',
      full_name: 'Ada Admin',
      email: 'ada@acme.test',
      password: 'correct horse battery',
    })
  })

  it('sends only the four fields, never a role or company', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/companies': { status: 201, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/register')
    await screen.findByLabelText(/company name/i)

    fillTheForm()
    press(/register/i)
    await screen.findByText(/welcome/i)

    const body = calls.find((c) => c.path === '/api/companies')?.body as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual(['company_name', 'email', 'full_name', 'password'])
  })

  it('tells the user the password rule before they hit it', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/register')

    const field = await screen.findByLabelText(/password/i)

    expect(field).toHaveAttribute('autocomplete', 'new-password')
    expect(field).toHaveAccessibleDescription(/at least 12 characters/i)
  })

  it('shows the server message when the password is too weak, and keeps the other answers', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/companies': {
        status: 422,
        body: { detail: 'Password must be at least 12 characters long.' },
      },
    })
    renderApp('/register')
    await screen.findByLabelText(/company name/i)
    fillTheForm()
    fillIn(/password/i, 'short')

    press(/register/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least 12 characters/i)
    expect(screen.getByLabelText(/company name/i)).toHaveValue('Acme Corp')
    expect(screen.getByLabelText(/email/i)).toHaveValue('ada@acme.test')
    expect(screen.getByLabelText(/password/i)).toHaveValue('')
  })

  it('shows the generic failure when the email is already registered', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/companies': {
        status: 400,
        body: {
          detail: "We couldn't create this account. If you already have one, log in instead.",
        },
      },
    })
    renderApp('/register')
    await screen.findByLabelText(/company name/i)
    fillTheForm()

    press(/register/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/if you already have one, log in/i)
    expect(within(screen.getByRole('main')).getByRole('link', { name: /log in/i })).toHaveAttribute(
      'href',
      '/login',
    )
  })

  it('cannot be submitted twice while the first attempt is running', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/register')
    await screen.findByLabelText(/company name/i)
    fillTheForm()
    const slow = vi.fn().mockReturnValue(new Promise(() => {}))
    vi.stubGlobal('fetch', slow)

    press(/register/i)

    expect(screen.getByRole('button', { name: /registering/i })).toBeDisabled()
    expect(slow).toHaveBeenCalledTimes(1)
  })

  it('sends someone who is already logged in home', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: { status: 'ok' } },
    })
    renderApp('/register')

    expect(await screen.findByText(/welcome, ada admin/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/company name/i)).not.toBeInTheDocument()
  })
})

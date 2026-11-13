import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, candidateUser, sessionFor, stubFetch, unverifiedCandidate } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

const GENERIC_FAILURE = {
  detail: "We couldn't create this account. If you already have one, log in instead.",
}

function fillTheForm() {
  fillIn(/your name/i, 'Cara Candidate')
  fillIn(/email/i, 'cara@example.test')
  fillIn(/password/i, 'correct horse battery')
}

describe('RegisterCandidatePage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('registers the candidate and asks them to verify their email', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/candidates': { status: 201, body: sessionFor(unverifiedCandidate) },
    })
    renderApp('/register/candidate')
    await screen.findByLabelText(/your name/i)

    fillTheForm()
    press(/create account/i)

    // Logged in but unverified: the profile page shows the "verify your email" screen.
    expect(await screen.findByText('Verify your email')).toBeInTheDocument()
    expect(screen.getByText(/cara@example\.test/)).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/api/candidates')!
    expect(post.method).toBe('POST')
    expect(post.body).toEqual({
      full_name: 'Cara Candidate',
      email: 'cara@example.test',
      password: 'correct horse battery',
    })
  })

  it('sends only the three fields, never a role or a company', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/candidates': { status: 201, body: sessionFor(unverifiedCandidate) },
    })
    renderApp('/register/candidate')
    await screen.findByLabelText(/your name/i)

    fillTheForm()
    press(/create account/i)

    await screen.findByText('Verify your email')
    expect(
      Object.keys(calls.find((c) => c.path === '/api/candidates')!.body as object).sort(),
    ).toEqual(['email', 'full_name', 'password'])
  })

  it('shows the server message, keeps the typed details and clears only the password', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/candidates': { status: 400, body: GENERIC_FAILURE },
    })
    renderApp('/register/candidate')
    await screen.findByLabelText(/your name/i)
    fillTheForm()

    press(/create account/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/log in instead/i)
    expect(screen.getByLabelText(/your name/i)).toHaveValue('Cara Candidate')
    expect(screen.getByLabelText(/email/i)).toHaveValue('cara@example.test')
    expect(screen.getByLabelText(/password/i)).toHaveValue('')
  })

  it('shows the password rule message from the server', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/candidates': {
        status: 422,
        body: { detail: 'Password must be at least 12 characters long.' },
      },
    })
    renderApp('/register/candidate')
    await screen.findByLabelText(/your name/i)
    fillTheForm()
    fillIn(/password/i, 'short')

    press(/create account/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least 12 characters/i)
  })

  it('does not send the form twice when it is submitted twice before the screen updates', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/candidates': { status: 201, body: sessionFor(unverifiedCandidate) },
    })
    renderApp('/register/candidate')
    await screen.findByLabelText(/your name/i)
    fillTheForm()

    const form = screen.getByLabelText(/your name/i).closest('form')!
    act(() => {
      fireEvent.submit(form)
      fireEvent.submit(form)
    })

    await screen.findByText('Verify your email')
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('returns to the page the visitor came from after registering', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/candidates': { status: 201, body: sessionFor(candidateUser) },
      'GET /api/public/jobs/j1': {
        status: 200,
        body: {
          id: 'j1',
          title: 'Backend Engineer',
          location: 'Oslo',
          description: 'Build.',
          department_name: 'Engineering',
          company_id: 'c1',
          company_name: 'Acme',
          opened_at: null,
        },
      },
    })
    renderApp('/register/candidate', { from: '/jobs/j1' })
    await screen.findByLabelText(/your name/i)
    fillTheForm()

    press(/create account/i)

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
  })

  it('ignores a "return to" address that leads off the site', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 401 },
      'POST /api/candidates': { status: 201, body: sessionFor(unverifiedCandidate) },
    })
    renderApp('/register/candidate', { from: '//evil.example' })
    await screen.findByLabelText(/your name/i)
    fillTheForm()

    press(/create account/i)

    expect(await screen.findByText('Verify your email')).toBeInTheDocument()
  })

  it('sends someone who is already logged in on to their own page', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(candidateUser) } })
    renderApp('/register/candidate')

    await waitFor(() => expect(screen.queryByLabelText(/your name/i)).not.toBeInTheDocument())
  })

  it('offers a way to log in instead', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/register/candidate')

    // One in the menu and one under the form; both lead to the login page.
    const links = await screen.findAllByRole('link', { name: /log in/i })
    expect(links.length).toBeGreaterThan(0)
    expect(links.every((link) => link.getAttribute('href') === '/login')).toBe(true)
  })
})

describe('the way to the candidate sign-up', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is in the menu for a visitor', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 }, 'GET /health': { status: 200, body: {} } })
    renderApp('/')

    // In the menu, and again on the home page.
    const links = await screen.findAllByRole('link', { name: /sign up as a candidate/i })
    expect(links.length).toBeGreaterThanOrEqual(2)
    expect(links.every((link) => link.getAttribute('href') === '/register/candidate')).toBe(true)
  })

  it('is on the login page', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })
    renderApp('/login')

    const links = await screen.findAllByRole('link', { name: /sign up as a candidate/i })
    expect(links.some((link) => link.getAttribute('href') === '/register/candidate')).toBe(true)
  })

  it('is not shown to someone who is logged in', async () => {
    stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) },
      'GET /health': { status: 200, body: {} },
    })
    renderApp('/')

    await screen.findByRole('button', { name: /log out/i })
    expect(screen.queryByRole('link', { name: /sign up as a candidate/i })).not.toBeInTheDocument()
  })
})

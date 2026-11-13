import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { Reply } from '@/test-utils'
import {
  adminUser,
  candidateUser,
  sessionFor,
  stubBackend,
  unverifiedCandidate,
} from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

interface ProfileData {
  full_name: string
  email: string
  phone: string | null
  location: string | null
  resume: null
}

/** A candidate and their profile, answering the way the real server does. */
function startServer(
  options: { user?: typeof candidateUser; profile?: Partial<ProfileData> } = {},
) {
  const user = options.user ?? candidateUser
  const state = {
    profile: {
      full_name: user.full_name,
      email: user.email,
      phone: null,
      location: null,
      resume: null,
      ...options.profile,
    } as ProfileData,
    failNext: {} as Record<string, Reply>,
  }

  const backend = stubBackend((call) => {
    const key = `${call.method} ${call.path}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /api/auth/me') {
      // The name in the header follows the profile, as it does on the real server.
      return { status: 200, body: sessionFor({ ...user, full_name: state.profile.full_name }) }
    }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/profile') return { status: 200, body: state.profile }
    if (key === 'PATCH /api/profile') {
      Object.assign(state.profile, call.body as Partial<ProfileData>)
      return { status: 200, body: state.profile }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function resetBrowserState() {
  setCsrfToken(null)
  setUnauthorizedHandler(null)
}

describe('ProfilePage', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('shows the candidate their own details', async () => {
    startServer({ profile: { phone: '+47 123 45 678', location: 'Oslo' } })
    renderApp('/profile')

    expect(await screen.findByRole('heading', { name: /your profile/i })).toBeInTheDocument()
    expect(await screen.findByLabelText(/your name/i)).toHaveValue('Cara Candidate')
    expect(screen.getByLabelText(/phone/i)).toHaveValue('+47 123 45 678')
    expect(screen.getByLabelText(/location/i)).toHaveValue('Oslo')
  })

  it('shows the email as text, since it cannot be changed here', async () => {
    startServer()
    renderApp('/profile')

    expect(await screen.findByText('cara@example.test')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^email$/i)).not.toBeInTheDocument()
  })

  it('saves changes with the CSRF token and says so', async () => {
    const { calls } = startServer()
    renderApp('/profile')
    await screen.findByLabelText(/phone/i)

    fillIn(/phone/i, '12345')
    fillIn(/location/i, 'Bergen')
    press(/save/i)

    expect(await screen.findByText(/profile saved/i)).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.path).toBe('/api/profile')
    expect(patch.body).toEqual({ full_name: 'Cara Candidate', phone: '12345', location: 'Bergen' })
    expect(patch.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('sends blank phone and location as null, which clears them', async () => {
    const { calls } = startServer({ profile: { phone: '12345', location: 'Oslo' } })
    renderApp('/profile')
    await screen.findByLabelText(/phone/i)

    fillIn(/phone/i, '   ')
    fillIn(/location/i, '')
    press(/save/i)

    await screen.findByText(/profile saved/i)
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({
      full_name: 'Cara Candidate',
      phone: null,
      location: null,
    })
  })

  it('updates the name shown in the header after a change', async () => {
    startServer()
    renderApp('/profile')
    await screen.findByLabelText(/your name/i)

    fillIn(/your name/i, 'Cara C. Candidate')
    press(/save/i)

    await screen.findByText(/profile saved/i)
    await waitFor(() =>
      expect(screen.getByText('Cara C. Candidate', { selector: 'span' })).toBeInTheDocument(),
    )
  })

  it('shows the server message and keeps what was typed when a change is refused', async () => {
    const server = startServer()
    server.state.failNext['PATCH /api/profile'] = {
      status: 422,
      body: { detail: 'Some of the entered values are not valid.' },
    }
    renderApp('/profile')
    await screen.findByLabelText(/phone/i)
    fillIn(/phone/i, '12345')

    press(/save/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/not valid/i)
    expect(screen.getByLabelText(/phone/i)).toHaveValue('12345')
    expect(screen.queryByText(/profile saved/i)).not.toBeInTheDocument()
  })

  it('does not save twice when submitted twice before the screen updates', async () => {
    const { calls } = startServer()
    renderApp('/profile')
    await screen.findByLabelText(/phone/i)
    fillIn(/phone/i, '12345')

    const form = screen.getByLabelText(/phone/i).closest('form')!
    act(() => {
      fireEvent.submit(form)
      fireEvent.submit(form)
    })

    await screen.findByText(/profile saved/i)
    expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
  })

  it('limits the boxes to what the server accepts', async () => {
    startServer()
    renderApp('/profile')

    expect(await screen.findByLabelText(/phone/i)).toHaveAttribute('maxlength', '30')
    expect(screen.getByLabelText(/location/i)).toHaveAttribute('maxlength', '200')
    expect(screen.getByLabelText(/your name/i)).toHaveAttribute('maxlength', '200')
    // The name is needed; phone and location are optional.
    expect(screen.getByLabelText(/your name/i)).toBeRequired()
    expect(screen.getByLabelText(/phone/i)).not.toBeRequired()
    expect(screen.getByLabelText(/location/i)).not.toBeRequired()
  })

  it('says so when the profile cannot be loaded, and lets the candidate try again', async () => {
    const server = startServer()
    server.state.failNext['GET /api/profile'] = { status: 500 }
    renderApp('/profile')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByLabelText(/phone/i)).toBeInTheDocument()
  })
})

describe('ProfilePage: who may open it', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('asks an unverified candidate to verify first, and never loads the profile', async () => {
    const { calls } = startServer({ user: unverifiedCandidate })
    renderApp('/profile')

    expect(await screen.findByText('Verify your email')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/profile')).toBe(false)
  })

  it('sends a visitor to log in, and back here afterwards', async () => {
    const { calls } = stubBackend((call) => {
      if (call.path === '/api/auth/me') return { status: 401, body: { detail: 'Not logged in.' } }
      return { status: 200, body: {} }
    })
    renderApp('/profile')

    // The login form (its title is not a heading, so look for its password box).
    expect(await screen.findByLabelText(/^password$/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/profile')).toBe(false)
  })

  it('shows company staff "not found"', async () => {
    const { calls } = startServer({ user: adminUser })
    renderApp('/profile')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/profile')).toBe(false)
  })

  it('gives a candidate Jobs and Profile in the menu', async () => {
    startServer()
    renderApp('/')

    const nav = await screen.findByRole('navigation', { name: 'Main' })
    const links = Array.from(nav.querySelectorAll('a')).map((a) => [
      a.textContent,
      a.getAttribute('href'),
    ])
    expect(links).toEqual([
      ['Jobs', '/jobs'],
      ['Profile', '/profile'],
    ])
  })
})

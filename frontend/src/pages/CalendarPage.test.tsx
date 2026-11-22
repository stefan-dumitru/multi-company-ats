import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDateTime } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, candidateUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import App from '@/App'
import { AuthProvider } from '@/auth/AuthContext'
import { press, renderApp } from '@/test-render'

interface CalendarState {
  configured: boolean
  connected: boolean
  connected_at: string | null
}

const GOOGLE_ADDRESS = 'https://accounts.google.com/o/oauth2/v2/auth?state=abc'
const SINCE = '2026-03-05T14:30:00Z'

function startServer(options: { user?: User; calendar?: Partial<CalendarState> } = {}) {
  const user = options.user ?? recruiterUser
  const state = {
    calendar: {
      configured: true,
      connected: false,
      connected_at: null,
      ...options.calendar,
    } as CalendarState,
    failNext: {} as Record<string, Reply>,
  }
  const backend = stubBackend((call) => {
    const key = `${call.method} ${new URL(call.path, 'http://app.test').pathname}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(user) }
    if (key === 'GET /api/calendar') return { status: 200, body: state.calendar }
    if (key === 'POST /api/calendar/connect') {
      return { status: 200, body: { url: GOOGLE_ADDRESS } }
    }
    if (key === 'DELETE /api/calendar/connection') {
      state.calendar = { ...state.calendar, connected: false, connected_at: null }
      return { status: 204, body: null }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })
  return { state, calls: backend.calls }
}

/** Shows the address the app is at, so a test can see what the page did to it. */
function AddressProbe() {
  const location = useLocation()
  return <output aria-label="address">{`${location.pathname}${location.search}`}</output>
}

/** Waits for a button to appear, then presses it. */
async function clickWhenThere(name: string) {
  fireEvent.click(await screen.findByRole('button', { name }))
}

describe('CalendarPage', () => {
  const assign = vi.fn()

  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
    assign.mockReset()
    vi.stubGlobal('location', { ...window.location, assign })
  })
  afterEach(() => vi.unstubAllGlobals())

  // ---- the four states --------------------------------------------------------------------

  it('says the server has no Google set up, and offers nothing to press', async () => {
    startServer({ calendar: { configured: false } })
    renderApp('/calendar')

    expect(await screen.findByText(/isn.t set up on this server/)).toBeInTheDocument()
    expect(screen.getByText(/still scheduled and emailed/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /connect|disconnect/i })).not.toBeInTheDocument()
  })

  it('offers to connect when the recruiter has not', async () => {
    startServer()
    renderApp('/calendar')

    expect(await screen.findByRole('button', { name: 'Connect Google Calendar' })).toBeEnabled()
    expect(screen.getByText(/Not connected/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Disconnect' })).not.toBeInTheDocument()
  })

  it('shows since when a recruiter is connected, and what that does and does not do', async () => {
    startServer({ calendar: { connected: true, connected_at: SINCE } })
    renderApp('/calendar')

    const since = await screen.findByText(/Connected since/)
    expect(since).toHaveTextContent(formatDateTime(SINCE))
    expect(screen.getByText(/primary calendar/)).toBeInTheDocument()
    expect(screen.getByText(/leaves the events already in Google/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Connect Google Calendar' }),
    ).not.toBeInTheDocument()
  })

  it('shows an error with a way to retry when the status cannot be loaded', async () => {
    const server = startServer()
    server.state.failNext['GET /api/calendar'] = { status: 500, body: {} }
    renderApp('/calendar')

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    press('Try again')
    expect(
      await screen.findByRole('button', { name: 'Connect Google Calendar' }),
    ).toBeInTheDocument()
  })

  // ---- connecting -------------------------------------------------------------------------

  it('sends the recruiter to the address Google gave, and asks for it once', async () => {
    const server = startServer()
    renderApp('/calendar')
    await clickWhenThere('Connect Google Calendar')

    await waitFor(() => expect(assign).toHaveBeenCalledWith(GOOGLE_ADDRESS))
    expect(assign).toHaveBeenCalledTimes(1)
    expect(server.calls.filter((call) => call.method === 'POST')).toHaveLength(1)
  })

  it('switches the button off while the address is being fetched', async () => {
    startServer()
    renderApp('/calendar')
    await clickWhenThere('Connect Google Calendar')

    expect(screen.getByRole('button', { name: /Connecting/ })).toBeDisabled()
    await waitFor(() => expect(assign).toHaveBeenCalled())
  })

  it('shows the failure and lets the recruiter try again when connecting fails', async () => {
    const server = startServer()
    server.state.failNext['POST /api/calendar/connect'] = {
      status: 503,
      body: { code: 'calendar_not_configured' },
    }
    renderApp('/calendar')
    await clickWhenThere('Connect Google Calendar')

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    expect(assign).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Connect Google Calendar' })).toBeEnabled()
  })

  // ---- disconnecting ----------------------------------------------------------------------

  it('asks before disconnecting, and does nothing when the recruiter keeps it', async () => {
    const server = startServer({ calendar: { connected: true, connected_at: SINCE } })
    renderApp('/calendar')
    await clickWhenThere('Disconnect')

    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/Existing events stay in Google/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Stay connected' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(server.calls.some((call) => call.method === 'DELETE')).toBe(false)
    expect(screen.getByText(/Connected since/)).toBeInTheDocument()
  })

  it('disconnects when confirmed and then shows the not-connected state', async () => {
    const server = startServer({ calendar: { connected: true, connected_at: SINCE } })
    renderApp('/calendar')
    await clickWhenThere('Disconnect')
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    expect(
      await screen.findByRole('button', { name: 'Connect Google Calendar' }),
    ).toBeInTheDocument()
    expect(server.calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
    expect(screen.queryByText(/Connected since/)).not.toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('keeps showing the connection and says why when disconnecting fails', async () => {
    const server = startServer({ calendar: { connected: true, connected_at: SINCE } })
    server.state.failNext['DELETE /api/calendar/connection'] = { status: 500, body: {} }
    renderApp('/calendar')
    await clickWhenThere('Disconnect')
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.getByText(/Connected since/)).toBeInTheDocument()
  })

  // ---- the way back from Google -----------------------------------------------------------

  it('says so when Google sends the recruiter back connected', async () => {
    startServer({ calendar: { connected: true, connected_at: SINCE } })
    renderApp('/calendar?connected=1')

    const note = await screen.findByText('Google Calendar is connected.')
    expect(note).toHaveAttribute('role', 'status')
  })

  it.each([
    ['access_denied', /did not allow access/],
    ['bad_state', /start again/],
    ['missing_code', /did not send/],
    ['google_unavailable', /could not be reached/],
    ['google_refused', /did not accept/],
    ['not_configured', /isn.t set up/],
    ['google_error', /Google reported a problem/],
  ])('explains the way back error %s in plain words', async (code, words) => {
    startServer()
    renderApp(`/calendar?error=${code}`)

    expect(await screen.findByRole('alert')).toHaveTextContent(words)
  })

  it('gives a generic message for an error code it does not know, never echoing the address', async () => {
    startServer()
    renderApp('/calendar?error=hello-world')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Google Calendar could not be connected.')
    expect(alert).not.toHaveTextContent('hello-world')
  })

  it('removes the note from the address so a refresh does not repeat it', async () => {
    startServer({ calendar: { connected: true, connected_at: SINCE } })
    render(
      <MemoryRouter initialEntries={['/calendar?error=access_denied']}>
        <AuthProvider>
          <App />
          <AddressProbe />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('did not allow access')
    await waitFor(() => expect(screen.getByLabelText('address')).toHaveTextContent(/^\/calendar$/))
    expect(screen.getByRole('alert')).toHaveTextContent('did not allow access') // still shown
  })

  it('shows the success note only for connected=1', async () => {
    startServer({ calendar: { connected: true, connected_at: SINCE } })
    renderApp('/calendar?connected=yes')

    await screen.findByText(/Connected since/)
    expect(screen.queryByText('Google Calendar is connected.')).not.toBeInTheDocument()
  })

  it('does not show a success note it was not told about', async () => {
    startServer({ calendar: { connected: true, connected_at: SINCE } })
    renderApp('/calendar')

    await screen.findByText(/Connected since/)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  // ---- who may open it --------------------------------------------------------------------

  it.each([
    ['a company admin', adminUser],
    ['a candidate', candidateUser],
  ])('is not a page %s can open', async (_who, user) => {
    startServer({ user })
    renderApp('/calendar')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('is in a recruiter’s menu', async () => {
    startServer()
    renderApp('/calendar')

    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Google Calendar' })).toHaveAttribute(
      'href',
      '/calendar',
    )
  })
})

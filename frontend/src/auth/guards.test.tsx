import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, MemoryRouter, useLocation } from 'react-router'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { adminUser, recruiterUser, sessionFor, stubFetch, unverifiedAdmin } from '@/test-utils'
import { AuthProvider } from './AuthContext'
import { RequireAuth, RequireRole } from './guards'

function LoginPage() {
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from
  return <p>login page, then back to {from}</p>
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/private" element={<p>private page</p>} />
            <Route element={<RequireRole roles={['company_admin']} />}>
              <Route path="/admin" element={<p>admin page</p>} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('route guards', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a loading message, not a flash of the login page, while the session is checked', () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))

    renderAt('/private')

    expect(screen.getByRole('status')).toHaveTextContent(/loading/i)
    expect(screen.queryByText(/login page/)).not.toBeInTheDocument()
  })

  it('sends a visitor to the login page and remembers where they were going', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })

    renderAt('/private?tab=2')

    expect(await screen.findByText('login page, then back to /private?tab=2')).toBeInTheDocument()
    expect(screen.queryByText('private page')).not.toBeInTheDocument()
  })

  it('lets a logged-in user through', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(recruiterUser) } })

    renderAt('/private')

    expect(await screen.findByText('private page')).toBeInTheDocument()
  })

  it('stops an unverified user at the door with the verify screen instead of the page', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(unverifiedAdmin) } })

    renderAt('/private')

    expect(await screen.findByText('Verify your email')).toBeInTheDocument()
    expect(screen.queryByText('private page')).not.toBeInTheDocument()
  })

  it('shows "not found", not "forbidden", to a role that may not use the page', async () => {
    // Same wording as an address that does not exist, so the page's existence is not revealed.
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(recruiterUser) } })

    renderAt('/admin')

    expect(await screen.findByRole('heading', { name: /page not found/i })).toBeInTheDocument()
    expect(screen.queryByText('admin page')).not.toBeInTheDocument()
  })

  it('lets the right role in', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) } })

    renderAt('/admin')

    expect(await screen.findByText('admin page')).toBeInTheDocument()
  })

  it('sends a visitor to login even for a role-restricted page', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })

    renderAt('/admin')

    expect(await screen.findByText('login page, then back to /admin')).toBeInTheDocument()
  })
})

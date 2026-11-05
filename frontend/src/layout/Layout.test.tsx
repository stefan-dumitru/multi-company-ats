import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { AuthProvider } from '@/auth/AuthContext'
import { adminUser, recruiterUser, sessionFor, stubFetch } from '@/test-utils'
import Layout from './Layout'

function renderLayout() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<p>page content</p>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Layout', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the page inside it, under the app name', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })

    renderLayout()

    expect(await screen.findByText('page content')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /applicant tracking system/i })).toHaveAttribute(
      'href',
      '/',
    )
  })

  it('offers a visitor no account menu', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })

    renderLayout()

    await screen.findByText('page content')
    expect(screen.queryByRole('button', { name: /log out/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  it('offers a visitor ways to log in or register a company', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 401 } })

    renderLayout()

    expect(await screen.findByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    expect(screen.getByRole('link', { name: 'Register your company' })).toHaveAttribute(
      'href',
      '/register',
    )
  })

  it('does not offer those to someone who is already logged in', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) } })

    renderLayout()

    await screen.findByText('Ada Admin')
    expect(screen.queryByRole('link', { name: 'Log in' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Register your company' })).not.toBeInTheDocument()
  })

  it('shows an admin who they are, a Users link and a log out button', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) } })

    renderLayout()

    expect(await screen.findByText('Ada Admin')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Users' })).toHaveAttribute('href', '/users')
    expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument()
  })

  it('hides links a role cannot use', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(recruiterUser) } })

    renderLayout()

    expect(await screen.findByText('Rae Recruiter')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
  })

  it('escapes what users typed instead of treating it as HTML', async () => {
    const sneaky = { ...adminUser, full_name: '<img src=x onerror=alert(1)>' }
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(sneaky) } })

    renderLayout()

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })

  it('logs out when the button is pressed', async () => {
    const { calls } = stubFetch({
      'GET /api/auth/me': { status: 200, body: sessionFor(adminUser, 'tok') },
      'POST /api/auth/logout': { status: 204 },
    })
    renderLayout()
    fireEvent.click(await screen.findByRole('button', { name: /log out/i }))

    expect(await screen.findByText('page content')).toBeInTheDocument()
    expect(screen.queryByText('Ada Admin')).not.toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/logout')?.headers['X-CSRF-Token']).toBe('tok')
  })

  it('says so when logging out failed, and keeps the user logged in', async () => {
    stubFetch({ 'GET /api/auth/me': { status: 200, body: sessionFor(adminUser) } })
    renderLayout()
    const button = await screen.findByRole('button', { name: /log out/i })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    fireEvent.click(button)

    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the server/i)
    expect(screen.getByText('Ada Admin')).toBeInTheDocument()
  })
})

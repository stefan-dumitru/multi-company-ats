import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { AuthProvider } from '@/auth/AuthContext'
import { stubFetch } from '@/test-utils'
import App from './App'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  setCsrfToken(null)
  setUnauthorizedHandler(null)
  stubFetch({
    'GET /health': { status: 200, body: { status: 'ok' } },
    'GET /api/auth/me': { status: 401 },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

it('renders the app title and the backend status on the home page', async () => {
  renderAt('/')

  expect(screen.getByRole('heading', { name: /applicant tracking system/i })).toBeInTheDocument()
  expect(await screen.findByText(/healthy/i)).toBeInTheDocument()
})

it('shows a not-found page for an address that does not exist', async () => {
  renderAt('/no/such/page')

  expect(await screen.findByRole('heading', { name: /page not found/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /home page/i })).toHaveAttribute('href', '/')
})

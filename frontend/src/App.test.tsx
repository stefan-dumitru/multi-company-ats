import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'

afterEach(() => {
  vi.unstubAllGlobals()
})

it('renders the app title and the backend status', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: 'ok' }) }),
  )

  render(<App />)

  expect(screen.getByRole('heading', { name: /applicant tracking system/i })).toBeInTheDocument()
  expect(await screen.findByText(/healthy/i)).toBeInTheDocument()
})

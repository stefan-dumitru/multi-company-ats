import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import HealthStatus from './HealthStatus'

function mockFetchResponse(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  )
}

describe('HealthStatus', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a checking message while waiting for the backend', () => {
    // A request that never settles keeps the component in its loading state.
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))

    render(<HealthStatus />)

    expect(screen.getByText(/checking/i)).toBeInTheDocument()
  })

  it('shows healthy when the backend reports ok', async () => {
    mockFetchResponse(200, { status: 'ok' })

    render(<HealthStatus />)

    expect(await screen.findByText(/healthy/i)).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/health')
  })

  it('shows unreachable when the backend answers 503', async () => {
    mockFetchResponse(503, { status: 'unavailable' })

    render(<HealthStatus />)

    expect(await screen.findByText(/unreachable/i)).toBeInTheDocument()
  })

  it('shows unreachable when the request fails entirely', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<HealthStatus />)

    expect(await screen.findByText(/unreachable/i)).toBeInTheDocument()
  })

  it('does not call a 200 healthy if the body is not ok', async () => {
    mockFetchResponse(200, { status: 'something else' })

    render(<HealthStatus />)

    expect(await screen.findByText(/unreachable/i)).toBeInTheDocument()
  })
})

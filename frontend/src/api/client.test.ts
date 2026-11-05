import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test-utils'
import { api, ApiError, setCsrfToken, setUnauthorizedHandler } from './client'

describe('api client', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends a plain GET with no body and returns the parsed answer', async () => {
    const { calls } = stubFetch({ 'GET /api/users': { status: 200, body: [{ id: '1' }] } })

    const result = await api<{ id: string }[]>('/api/users')

    expect(result).toEqual([{ id: '1' }])
    expect(calls[0]).toMatchObject({ method: 'GET', path: '/api/users', body: undefined })
    expect(calls[0].headers['Content-Type']).toBeUndefined()
  })

  it('sends JSON bodies with a JSON content type', async () => {
    const { calls } = stubFetch({ 'POST /api/invitations': { status: 201, body: {} } })

    await api('/api/invitations', { method: 'POST', body: { email: 'x@y.test' } })

    expect(calls[0].body).toEqual({ email: 'x@y.test' })
    expect(calls[0].headers['Content-Type']).toBe('application/json')
  })

  it('adds the CSRF token to changing requests, but not to reads', async () => {
    const { calls } = stubFetch({
      'GET /api/users': { status: 200, body: [] },
      'POST /api/auth/logout': { status: 204 },
      'PATCH /api/users/1/role': { status: 200, body: {} },
    })
    setCsrfToken('secret-token')

    await api('/api/users')
    await api('/api/auth/logout', { method: 'POST' })
    await api('/api/users/1/role', { method: 'PATCH', body: { role: 'recruiter' } })

    expect(calls[0].headers['X-CSRF-Token']).toBeUndefined()
    expect(calls[1].headers['X-CSRF-Token']).toBe('secret-token')
    expect(calls[2].headers['X-CSRF-Token']).toBe('secret-token')
  })

  it('sends no CSRF header when there is no token yet', async () => {
    const { calls } = stubFetch({ 'POST /api/auth/login': { status: 200, body: {} } })

    await api('/api/auth/login', { method: 'POST', body: {} })

    expect(calls[0].headers['X-CSRF-Token']).toBeUndefined()
  })

  it('returns undefined when the server answers 204 with no content', async () => {
    stubFetch({ 'POST /api/auth/logout': { status: 204 } })

    expect(await api('/api/auth/logout', { method: 'POST' })).toBeUndefined()
  })

  it("turns the server's message into an ApiError", async () => {
    stubFetch({
      'POST /api/invitations': {
        status: 409,
        body: { detail: 'That email already has an account.' },
      },
    })

    const failure = await api('/api/invitations', { method: 'POST', body: {} }).catch((e) => e)

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure.status).toBe(409)
    expect(failure.message).toBe('That email already has an account.')
  })

  it('does not dump raw validation lists on the user', async () => {
    stubFetch({
      'POST /api/companies': {
        status: 422,
        body: { detail: [{ loc: ['body', 'email'], msg: 'x' }] },
      },
    })

    const failure = await api('/api/companies', { method: 'POST', body: {} }).catch((e) => e)

    expect(failure.status).toBe(422)
    expect(failure.message).toBe('Some of the entered values are not valid.')
  })

  it('never shows server error text for a 5xx', async () => {
    stubFetch({
      'GET /api/users': { status: 500, body: { detail: 'Traceback: secret internals' } },
    })

    const failure = await api('/api/users').catch((e) => e)

    expect(failure.status).toBe(500)
    expect(failure.message).toBe('Something went wrong. Please try again.')
  })

  it('uses a generic message when the error body is not JSON (for example a proxy page)', async () => {
    stubFetch({ 'GET /api/users': { status: 502 } })

    const failure = await api('/api/users').catch((e) => e)

    expect(failure.status).toBe(502)
    expect(failure.message).toBe('Something went wrong. Please try again.')
  })

  it('reports an unreachable server as an ApiError with status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    const failure = await api('/api/users').catch((e) => e)

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure.status).toBe(0)
    expect(failure.message).toMatch(/cannot reach the server/i)
  })

  it('tells the unauthorized handler when a request comes back 401', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    stubFetch({ 'GET /api/users': { status: 401, body: { detail: 'Not logged in.' } } })

    await api('/api/users').catch(() => undefined)

    expect(handler).toHaveBeenCalledOnce()
  })

  it('does not treat a 401 as an expired session when one was expected (login, /me)', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    stubFetch({
      'POST /api/auth/login': { status: 401, body: { detail: 'Invalid email or password.' } },
    })

    await api('/api/auth/login', { method: 'POST', body: {}, expectUnauthorized: true }).catch(
      () => undefined,
    )

    expect(handler).not.toHaveBeenCalled()
  })

  it('does not call the unauthorized handler for other errors', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    stubFetch({
      'GET /api/users': { status: 403, body: { detail: 'You do not have access to this.' } },
    })

    await api('/api/users').catch(() => undefined)

    expect(handler).not.toHaveBeenCalled()
  })
})

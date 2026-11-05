/** The one place the app talks to the backend. Pages call `api(...)`, never `fetch` directly. */

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    // Status 0 means the request never got an answer (server down, no network).
    this.status = status
  }
}

const GENERIC_ERROR = 'Something went wrong. Please try again.'
const INVALID_VALUES = 'Some of the entered values are not valid.'
const UNREACHABLE = 'Cannot reach the server. Check your connection and try again.'

// Kept in memory only, never in localStorage: a script injected into the page could read storage.
// A page refresh asks the server for it again (GET /api/auth/me).
let csrfToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

/** Called when any request is answered 401, i.e. the session ended while the user was working. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Set for calls where 401 is a normal answer (login with a wrong password, "who am I?"). */
  expectUnauthorized?: boolean
}

async function errorMessage(response: Response): Promise<string> {
  // Never show server error text for a 5xx: it can contain internals.
  if (response.status >= 500) {
    return GENERIC_ERROR
  }
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') {
      return body.detail
    }
    if (Array.isArray(body.detail)) {
      return INVALID_VALUES
    }
  } catch {
    // Not JSON, for example an error page from a proxy: fall through to the generic message.
  }
  return GENERIC_ERROR
}

export async function api<T = void>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = {}
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  // Only requests that change data need the token (the server checks the same rule).
  if (method !== 'GET' && csrfToken !== null) {
    headers['X-CSRF-Token'] = csrfToken
  }

  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, UNREACHABLE)
  }

  if (response.status === 401 && !options.expectUnauthorized) {
    onUnauthorized?.()
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

import { vi } from 'vitest'
import type { User } from '@/auth/types'

export interface Reply {
  status: number
  body?: unknown
}

export interface RecordedCall {
  method: string
  path: string
  headers: Record<string, string>
  body: unknown
}

/**
 * Replaces fetch with a fake that answers by "METHOD /path" and records every call.
 * A request nobody planned for fails the test loudly instead of being quietly answered.
 */
export function stubFetch(routes: Record<string, Reply | (() => Reply)>) {
  const calls: RecordedCall[] = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path,
        headers: (init?.headers ?? {}) as Record<string, string>,
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
      })
      const route = routes[`${method} ${path}`]
      if (route === undefined) {
        throw new Error(`Unexpected request in test: ${method} ${path}`)
      }
      const { status, body } = typeof route === 'function' ? route() : route
      return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => {
          if (body === undefined) {
            throw new SyntaxError('Unexpected end of JSON input')
          }
          return body
        },
      }
    }),
  )

  return { calls }
}

export const adminUser: User = {
  id: 'u-admin',
  email: 'ada@acme.test',
  full_name: 'Ada Admin',
  role: 'company_admin',
  company_id: 'c-1',
}

export const recruiterUser: User = {
  id: 'u-rec',
  email: 'rae@acme.test',
  full_name: 'Rae Recruiter',
  role: 'recruiter',
  company_id: 'c-1',
}

export function sessionFor(user: User, csrfToken = 'csrf-token-1') {
  return { user, csrf_token: csrfToken }
}

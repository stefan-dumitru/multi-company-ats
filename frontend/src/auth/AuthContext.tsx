import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { SessionInfo, User } from './types'

type AuthState =
  | { status: 'loading' }
  // `notice` explains why the user is logged out when it was not their choice.
  | { status: 'anonymous'; notice: string | null }
  | { status: 'authenticated'; user: User }

interface AuthContextValue {
  state: AuthState
  /** Remember a session the server just created (login, company signup, invitation). */
  startSession: (info: SessionInfo) => void
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const SESSION_EXPIRED = 'Your session has expired. Please log in again.'

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  const startSession = useCallback((info: SessionInfo) => {
    setCsrfToken(info.csrf_token)
    setState({ status: 'authenticated', user: info.user })
  }, [])

  const endSession = useCallback((notice: string | null) => {
    setCsrfToken(null)
    setState({ status: 'anonymous', notice })
  }, [])

  useEffect(() => {
    // If the page goes away before the answer arrives, do not update state on it.
    let ignoreAnswer = false

    // A request answered 401 while logged in means the session ended (idle timeout, or the account
    // was deactivated): send the user to log in again, with an explanation.
    setUnauthorizedHandler(() => endSession(SESSION_EXPIRED))

    api<SessionInfo>('/api/auth/me', { expectUnauthorized: true })
      .then((info) => {
        if (!ignoreAnswer) startSession(info)
      })
      .catch(() => {
        // 401 means nobody is logged in. Any other failure (server down) also lands here: the
        // visitor sees the logged-out app, and logging in will report the real problem.
        if (!ignoreAnswer) endSession(null)
      })

    return () => {
      ignoreAnswer = true
      setUnauthorizedHandler(null)
    }
  }, [startSession, endSession])

  const login = useCallback(
    async (email: string, password: string) => {
      const info = await api<SessionInfo>('/api/auth/login', {
        method: 'POST',
        body: { email, password },
        expectUnauthorized: true, // a wrong password is a normal 401, not an expired session
      })
      startSession(info)
    },
    [startSession],
  )

  const logout = useCallback(async () => {
    // If the request fails the session still exists on the server, so we must not pretend to be
    // logged out: the error reaches the caller and the user stays logged in.
    await api('/api/auth/logout', { method: 'POST' })
    endSession(null)
  }, [endSession])

  const value = useMemo(
    () => ({ state, startSession, login, logout }),
    [state, startSession, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (value === null) {
    throw new Error('useAuth must be used inside an AuthProvider.')
  }
  return value
}

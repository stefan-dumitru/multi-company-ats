import { Navigate, Outlet, useLocation } from 'react-router'
import NotFoundPage from '@/pages/NotFoundPage'
import VerifyEmailRequiredPage from '@/pages/VerifyEmailRequiredPage'
import { useAuth } from './AuthContext'
import type { Role } from './types'

/** Pages inside this need a logged-in user; visitors are sent to log in, then brought back. */
export function RequireAuth() {
  const { state } = useAuth()
  const location = useLocation()

  if (state.status === 'loading') {
    // Wait for the session check instead of flashing the login page at someone who is logged in.
    return <p role="status">Loading…</p>
  }
  if (state.status === 'anonymous') {
    const from = location.pathname + location.search
    return <Navigate to="/login" replace state={{ from }} />
  }
  if (state.user.email_verified_at === null) {
    // Logged in, but may do nothing else until the address is verified. The server enforces this
    // too; this just shows why instead of a page full of errors.
    return <VerifyEmailRequiredPage email={state.user.email} />
  }
  return <Outlet />
}

/**
 * Pages inside this are for certain roles only. Use inside RequireAuth.
 *
 * This only decides what the screen shows. The server enforces who may do what, and answers "not
 * found" for things outside the caller's scope, so this page says the same.
 */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { state } = useAuth()

  if (state.status !== 'authenticated' || !roles.includes(state.user.role)) {
    return <NotFoundPage />
  }
  return <Outlet />
}

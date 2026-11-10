import { useState } from 'react'
import { Link, Outlet } from 'react-router'
import { useAuth } from '@/auth/AuthContext'
import { navItemsFor } from '@/auth/navigation'
import { Button } from '@/components/ui/button'

export default function Layout() {
  const { state, logout } = useAuth()
  const [logoutError, setLogoutError] = useState('')

  async function handleLogout() {
    setLogoutError('')
    try {
      await logout()
    } catch (error) {
      // Still logged in on the server, so stay logged in here and say why.
      setLogoutError(error instanceof Error ? error.message : 'Could not log out.')
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-4 px-4 py-3">
          <Link to="/" className="font-semibold">
            Applicant Tracking System
          </Link>
          {state.status === 'authenticated' && (
            <>
              <nav aria-label="Main" className="flex gap-3">
                {navItemsFor(state.user.role).map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    className="text-sm underline-offset-4 hover:underline"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
              <div className="ml-auto flex items-center gap-3">
                <span className="text-sm text-muted-foreground">{state.user.full_name}</span>
                <Button variant="outline" size="sm" onClick={() => void handleLogout()}>
                  Log out
                </Button>
              </div>
            </>
          )}
          {state.status === 'anonymous' && (
            <nav aria-label="Account" className="ml-auto flex items-center gap-4 text-sm">
              <Link to="/jobs" className="underline-offset-4 hover:underline">
                Find jobs
              </Link>
              <Link to="/login" className="underline-offset-4 hover:underline">
                Log in
              </Link>
              <Link to="/register" className="underline-offset-4 hover:underline">
                Register your company
              </Link>
            </nav>
          )}
        </div>
        {logoutError && (
          <p role="alert" className="mx-auto max-w-4xl px-4 pb-3 text-sm text-destructive">
            {logoutError}
          </p>
        )}
      </header>
      <main className="mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { messageOf } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import AuthCard from '@/components/AuthCard'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

/**
 * Where to send the user after logging in: the page they were trying to open, if it is a page of
 * this app. Anything else ("//evil.example", "https://...") would make the login page a way to
 * bounce people to another site, so it is ignored.
 */
function returnPath(routerState: unknown): string {
  const from = (routerState as { from?: unknown } | null)?.from
  if (typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')) {
    return from
  }
  return '/'
}

export default function LoginPage() {
  const { state, login } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (state.status === 'loading') {
    return <p role="status">Loading…</p>
  }
  if (state.status === 'authenticated') {
    return <Navigate to={returnPath(location.state)} replace />
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      await login(email, password)
    } catch (failure) {
      setError(messageOf(failure))
      setPassword('') // keep the email, but never leave a rejected password sitting in the field
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard title="Log in">
      {state.notice && (
        <p role="status" className="text-sm text-muted-foreground">
          {state.notice}
        </p>
      )}
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField
          id="email"
          label="Email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={setEmail}
        />
        <FormField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={setPassword}
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? 'Logging in…' : 'Log in'}
        </Button>
      </form>
      <p className="text-sm">
        <Link to="/forgot-password" className="text-primary underline underline-offset-4">
          Forgot your password?
        </Link>
      </p>
      <p className="text-sm text-muted-foreground">
        New here?{' '}
        <Link to="/register" className="text-primary underline underline-offset-4">
          Register your company
        </Link>
      </p>
    </AuthCard>
  )
}

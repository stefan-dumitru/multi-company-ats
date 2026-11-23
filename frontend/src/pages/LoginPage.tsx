import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useSearchParams } from 'react-router'
import { messageOf } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { googleErrorMessage } from '@/auth/googleLogin'
import { afterLoginPathFor } from '@/auth/navigation'
import { safeReturnPath } from '@/auth/returnPath'
import AuthCard from '@/components/AuthCard'
import FormField from '@/components/FormField'
import GoogleSignIn from '@/components/GoogleSignIn'
import { Button } from '@/components/ui/button'

export default function LoginPage() {
  const { state, login } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  // What Google sent the browser back with, read once and then removed from the address, so a
  // refresh does not repeat it. The words come from our own table, never from the address.
  const [googleProblem] = useState(() => {
    const code = searchParams.get('google_error')
    return code === null ? '' : googleErrorMessage(code)
  })

  useEffect(() => {
    if (searchParams.has('google_error')) {
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  if (state.status === 'loading') {
    return <p role="status">Loading…</p>
  }
  if (state.status === 'authenticated') {
    const fallback = afterLoginPathFor(state.user.role)
    return <Navigate to={safeReturnPath(location.state, fallback)} replace />
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
      {googleProblem && (
        <p role="alert" className="text-sm text-destructive">
          {googleProblem}
        </p>
      )}
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
      <GoogleSignIn />
      <p className="text-sm">
        <Link to="/forgot-password" className="text-primary underline underline-offset-4">
          Forgot your password?
        </Link>
      </p>
      <p className="text-sm text-muted-foreground">
        New here?{' '}
        <Link to="/register/candidate" className="text-primary underline underline-offset-4">
          Sign up as a candidate
        </Link>{' '}
        or{' '}
        <Link to="/register" className="text-primary underline underline-offset-4">
          Register your company
        </Link>
      </p>
    </AuthCard>
  )
}

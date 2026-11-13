import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { api, messageOf } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { landingPathFor } from '@/auth/navigation'
import { safeReturnPath } from '@/auth/returnPath'
import type { SessionInfo } from '@/auth/types'
import AuthCard from '@/components/AuthCard'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

/** Sign-up for job seekers. (Companies register on their own page.) */
export default function RegisterCandidatePage() {
  const { state, startSession } = useAuth()
  const location = useLocation()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const busy = useRef(false) // stops a second send before React has re-rendered the button

  if (state.status === 'loading') {
    return <p role="status">Loading…</p>
  }
  if (state.status === 'authenticated') {
    // Also what happens right after registering: starting the session makes this page re-render
    // as "authenticated", and this one redirect is the only thing that moves the user on. A visitor
    // who came from a job page goes back to it; everyone else lands on their profile, where an
    // unverified account is told to check its email.
    return <Navigate to={safeReturnPath(location.state, landingPathFor(state.user.role))} replace />
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy.current) return
    busy.current = true
    setError('')
    setSubmitting(true)
    try {
      const info = await api<SessionInfo>('/api/candidates', {
        method: 'POST',
        body: { full_name: fullName, email, password },
        expectUnauthorized: true,
      })
      startSession(info)
    } catch (failure) {
      setError(messageOf(failure))
      setPassword('')
    } finally {
      busy.current = false
      setSubmitting(false)
    }
  }

  return (
    <AuthCard
      title="Create your account"
      description="Find jobs, apply, and follow your applications in one place."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField
          id="full-name"
          label="Your name"
          autoComplete="name"
          value={fullName}
          onChange={setFullName}
          maxLength={200}
        />
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
          autoComplete="new-password"
          hint="At least 12 characters. A long phrase is easier to remember than symbols."
          value={password}
          onChange={setPassword}
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create account'}
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link to="/login" className="text-primary underline underline-offset-4">
          Log in
        </Link>
      </p>
    </AuthCard>
  )
}

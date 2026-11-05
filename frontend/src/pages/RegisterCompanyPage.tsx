import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate } from 'react-router'
import { api, messageOf } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { landingPathFor } from '@/auth/navigation'
import type { SessionInfo } from '@/auth/types'
import AuthCard from '@/components/AuthCard'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

export default function RegisterCompanyPage() {
  const { state, startSession } = useAuth()
  const [companyName, setCompanyName] = useState('')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (state.status === 'loading') {
    return <p role="status">Loading…</p>
  }
  if (state.status === 'authenticated') {
    // Also what happens right after registering: starting the session makes this page re-render
    // as "authenticated", and this one redirect is the only thing that moves the user on.
    return <Navigate to={landingPathFor(state.user.role)} replace />
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      const info = await api<SessionInfo>('/api/companies', {
        method: 'POST',
        body: { company_name: companyName, full_name: fullName, email, password },
        expectUnauthorized: true,
      })
      startSession(info)
    } catch (failure) {
      setError(messageOf(failure))
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard
      title="Register your company"
      description="You become the company's first admin and can invite your team afterwards."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField
          id="company-name"
          label="Company name"
          autoComplete="organization"
          value={companyName}
          onChange={setCompanyName}
        />
        <FormField
          id="full-name"
          label="Your name"
          autoComplete="name"
          value={fullName}
          onChange={setFullName}
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
          {submitting ? 'Registering…' : 'Register'}
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

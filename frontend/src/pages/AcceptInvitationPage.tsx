import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api, messageOf } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import type { SessionInfo } from '@/auth/types'
import AuthCard from '@/components/AuthCard'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

export default function AcceptInvitationPage() {
  const { startSession } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!token) {
    return (
      <AuthCard title="Join your team">
        <p role="alert" className="text-sm text-destructive">
          This invitation link is invalid or incomplete. Ask your admin to send it again.
        </p>
        <Link to="/login" className="text-sm text-primary underline underline-offset-4">
          Log in
        </Link>
      </AuthCard>
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      // Only the three things the person chose or holds. Their role and company come from the
      // invitation on the server.
      const info = await api<SessionInfo>('/api/invitations/accept', {
        method: 'POST',
        body: { token, full_name: fullName, password },
        expectUnauthorized: true,
      })
      startSession(info)
      // Replace, so the secret link is not left in the browser history.
      navigate('/', { replace: true })
    } catch (failure) {
      setError(messageOf(failure))
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard
      title="Join your team"
      description="Choose your name and a password to finish creating your account."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField
          id="full-name"
          label="Your name"
          autoComplete="name"
          value={fullName}
          onChange={setFullName}
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
          {submitting ? 'Joining…' : 'Join'}
        </Button>
      </form>
    </AuthCard>
  )
}

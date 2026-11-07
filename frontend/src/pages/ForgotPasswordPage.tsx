import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router'
import { api, messageOf } from '@/api/client'
import AuthCard from '@/components/AuthCard'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

/** Asks for a password reset link. The answer is the same whether or not the address has an account. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      await api('/api/auth/forgot-password', { method: 'POST', body: { email } })
      setSent(true)
    } catch (failure) {
      setError(messageOf(failure))
    } finally {
      setSubmitting(false)
    }
  }

  if (sent) {
    return (
      <AuthCard title="Check your email">
        {/* Deliberately not "we sent a link to <address>": that would confirm the account exists. */}
        <p role="status" className="text-sm">
          If an account exists for that address, we have sent a link to reset the password. It works
          once and expires after 1 hour.
        </p>
        <p className="text-sm text-muted-foreground">
          Nothing arrived? Check your spam folder, or{' '}
          <Link to="/login" className="text-primary underline underline-offset-4">
            go back to log in
          </Link>
          .
        </p>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title="Forgot your password?"
      description="Enter your email and we will send you a link to choose a new one."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField
          id="email"
          label="Email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={setEmail}
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? 'Sending…' : 'Send reset link'}
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">
        <Link to="/login" className="text-primary underline underline-offset-4">
          Back to log in
        </Link>
      </p>
    </AuthCard>
  )
}

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api, messageOf } from '@/api/client'
import AuthCard from '@/components/AuthCard'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

/** The page the link in the reset email opens: choose a new password. */
export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [linkIsBad, setLinkIsBad] = useState(false)
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  if (!token) {
    return (
      <AuthCard title="Choose a new password">
        <p role="alert" className="text-sm text-destructive">
          This reset link is incomplete. Use the link from the email we sent you, or ask for a new
          one.
        </p>
        <Link to="/forgot-password" className="text-sm text-primary underline underline-offset-4">
          Ask for a new link
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
      await api('/api/auth/reset-password', { method: 'POST', body: { token, password } })
      setDone(true)
    } catch (failure) {
      setError(messageOf(failure))
      // 400 means the link itself is bad (used, expired, forged); anything else, such as a weak
      // password, can be fixed by trying again with the same link.
      setLinkIsBad(failure instanceof Error && 'status' in failure && failure.status === 400)
      setPassword('') // never leave a rejected password sitting in the field
    } finally {
      setSubmitting(false)
    }
  }

  if (done) {
    return (
      <AuthCard title="Password changed">
        <p className="text-sm">
          Your password was changed. For your safety you were logged out everywhere.
        </p>
        <Link to="/login" className="text-sm text-primary underline underline-offset-4">
          Log in
        </Link>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Choose a new password">
      {linkIsBad ? (
        <>
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
          <Link to="/forgot-password" className="text-sm text-primary underline underline-offset-4">
            Ask for a new link
          </Link>
        </>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField
            id="new-password"
            label="New password"
            type="password"
            autoComplete="new-password"
            hint="At least 12 characters."
            value={password}
            onChange={setPassword}
          />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? 'Saving…' : 'Set new password'}
          </Button>
        </form>
      )}
    </AuthCard>
  )
}

import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api, messageOf } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import AuthCard from '@/components/AuthCard'
import ResendVerification from '@/components/ResendVerification'

type Outcome = { kind: 'working' } | { kind: 'verified' } | { kind: 'failed'; message: string }

/** The page the link in the verification email opens. */
export default function VerifyEmailPage() {
  const { state, refreshUser } = useAuth()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [outcome, setOutcome] = useState<Outcome>({ kind: 'working' })
  const [stale, setStale] = useState(false)
  // A link works once. React may run this effect twice in development; the second call would
  // fail and show a false error, so each link is only ever sent once.
  const sentFor = useRef<string | null>(null)

  useEffect(() => {
    if (!token || sentFor.current === token) return
    sentFor.current = token
    api('/api/auth/verify-email', { method: 'POST', body: { token } })
      .then(async () => {
        setOutcome({ kind: 'verified' })
        // If this browser is logged in, the app must learn that the address is now verified.
        try {
          await refreshUser()
        } catch {
          setStale(true) // verified on the server; this page just could not re-read the account
        }
      })
      .catch((failure) => setOutcome({ kind: 'failed', message: messageOf(failure) }))
  }, [token, refreshUser])

  if (!token) {
    return (
      <AuthCard title="Verify your email">
        <p role="alert" className="text-sm text-destructive">
          This verification link is incomplete. Use the link from the email we sent you, or log in
          to get a new one.
        </p>
        <Link to="/login" className="text-sm text-primary underline underline-offset-4">
          Log in
        </Link>
      </AuthCard>
    )
  }

  const loggedIn = state.status === 'authenticated'
  // Opening a link a second time (or refreshing) fails because it was already used. Someone who
  // is verified has nothing to worry about, so do not show them an error.
  const alreadyVerified = loggedIn && state.user.email_verified_at !== null

  if (outcome.kind === 'verified' || (outcome.kind === 'failed' && alreadyVerified)) {
    return (
      <AuthCard title="Email verified">
        <p className="text-sm">Your email address is verified. Thank you.</p>
        {stale && (
          <p className="text-sm text-muted-foreground">
            Reload the page if the app still asks you to verify.
          </p>
        )}
        {loggedIn ? (
          <Link to="/" className="text-sm text-primary underline underline-offset-4">
            Continue
          </Link>
        ) : (
          <Link to="/login" className="text-sm text-primary underline underline-offset-4">
            Log in
          </Link>
        )}
      </AuthCard>
    )
  }

  if (outcome.kind === 'failed') {
    return (
      <AuthCard title="Verify your email">
        <p role="alert" className="text-sm text-destructive">
          {outcome.message}
        </p>
        {loggedIn ? (
          <ResendVerification email={state.user.email} />
        ) : (
          <p className="text-sm text-muted-foreground">
            <Link to="/login" className="text-primary underline underline-offset-4">
              Log in
            </Link>{' '}
            to get a new link.
          </p>
        )}
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Verify your email">
      <p role="status" className="text-sm">
        Verifying…
      </p>
    </AuthCard>
  )
}

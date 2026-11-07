import AuthCard from '@/components/AuthCard'
import ResendVerification from '@/components/ResendVerification'

/** Shown instead of the app to a logged-in user whose email address is not verified yet. */
export default function VerifyEmailRequiredPage({ email }: { email: string }) {
  return (
    <AuthCard title="Verify your email" description="One quick step before you can use the app.">
      <p className="text-sm">
        We sent a link to <strong>{email}</strong>. Open it to confirm that this address is yours.
        The link works once and expires after 24 hours.
      </p>
      <p className="text-sm text-muted-foreground">
        Nothing arrived? Check your spam folder, or ask for a new link below.
      </p>
      <ResendVerification email={email} />
    </AuthCard>
  )
}

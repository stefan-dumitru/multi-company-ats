import { Link } from 'react-router'
import { useAuth } from '@/auth/AuthContext'
import ResendVerification from '@/components/ResendVerification'
import HealthStatus from '@/HealthStatus'

export default function HomePage() {
  const { state } = useAuth()

  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">Applicant Tracking System</h1>
      {state.status === 'authenticated' && (
        <>
          <p>Welcome, {state.user.full_name}.</p>
          {state.user.email_verified_at === null && (
            // The server already refuses everything else; this explains why and offers a way out.
            <div className="space-y-2 rounded-md border p-4">
              <p className="text-sm">
                Your email address is not verified yet. Open the link we sent to{' '}
                <strong>{state.user.email}</strong> to unlock the app.
              </p>
              <ResendVerification email={state.user.email} />
            </div>
          )}
          {state.user.email_verified_at !== null && state.user.role === 'company_admin' && (
            <p>
              <Link to="/users" className="text-primary underline underline-offset-4">
                Manage users
              </Link>{' '}
              to invite your team.
            </p>
          )}
        </>
      )}
      {state.status === 'anonymous' && (
        <p>
          <Link to="/register" className="text-primary underline underline-offset-4">
            Register your company
          </Link>{' '}
          or{' '}
          <Link to="/login" className="text-primary underline underline-offset-4">
            log in
          </Link>
          .
        </p>
      )}
      <HealthStatus />
    </section>
  )
}

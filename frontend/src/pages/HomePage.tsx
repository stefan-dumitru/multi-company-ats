import { Link } from 'react-router'
import { useAuth } from '@/auth/AuthContext'
import HealthStatus from '@/HealthStatus'

export default function HomePage() {
  const { state } = useAuth()

  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">Applicant Tracking System</h1>
      {state.status === 'authenticated' && <p>Welcome, {state.user.full_name}.</p>}
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

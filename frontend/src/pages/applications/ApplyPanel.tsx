import { useState } from 'react'
import { Link } from 'react-router'
import { api, messageOf } from '@/api/client'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import { useAuth } from '@/auth/AuthContext'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import type { MyApplication } from './types'

const LINK = 'text-primary underline underline-offset-4'

/** What the job page offers about applying, depending on who is looking. */
export default function ApplyPanel({ jobId }: { jobId: string }) {
  const { state } = useAuth()

  if (state.status === 'loading') return null
  if (state.status === 'anonymous') {
    // `from` brings the visitor back to this job after logging in or registering.
    const from = { from: `/jobs/${jobId}` }
    return (
      <p>
        <span className="font-medium">Log in or register to apply.</span>{' '}
        <Link to="/login" state={from} className={LINK}>
          Log in
        </Link>{' '}
        or{' '}
        <Link to="/register/candidate" state={from} className={LINK}>
          register
        </Link>
      </p>
    )
  }
  // Staff apply to nothing: show nothing rather than a button that could only fail.
  if (state.user.role !== 'candidate') return null
  if (state.user.email_verified_at === null) {
    return (
      <p>
        Verify your email to apply. You can do that from{' '}
        <Link to="/profile" className={LINK}>
          your profile
        </Link>
        .
      </p>
    )
  }
  return <CandidateApply jobId={jobId} />
}

/** For a candidate who may apply: their resume and any earlier application are looked up here, so
 * visitors and staff never trigger those requests. */
function CandidateApply({ jobId }: { jobId: string }) {
  const profile = useResource<{ resume: object | null }>('/api/profile')
  const earlier = useResource<Page<MyApplication>>(
    `/api/applications?job_id=${encodeURIComponent(jobId)}`,
  )
  const [justApplied, setJustApplied] = useState<MyApplication | null>(null)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')

  async function apply() {
    setError('')
    setApplying(true)
    try {
      setJustApplied(
        await api<MyApplication>('/api/applications', {
          method: 'POST',
          body: { job_id: jobId },
        }),
      )
    } catch (failure) {
      setError(messageOf(failure))
    } finally {
      setApplying(false)
    }
  }

  const application = justApplied ?? earlier.data?.items[0] ?? null
  if (application) {
    return (
      <p>
        {application.stage === 'withdrawn'
          ? 'You withdrew your application. '
          : `You applied on ${formatDate(application.applied_at)} `}
        <Link to="/applications" className={LINK}>
          My applications
        </Link>
      </p>
    )
  }

  const failure = profile.data === null ? profile : earlier.data === null ? earlier : null
  if (failure) {
    if (failure.loading) return <p role="status">Loading…</p>
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-destructive">
          {failure.error}
        </p>
        <Button variant="outline" size="sm" onClick={failure.reload}>
          Try again
        </Button>
      </div>
    )
  }
  if (profile.data?.resume === null) {
    return (
      <p>
        Add your resume to apply. You can do that from{' '}
        <Link to="/profile" className={LINK}>
          your profile
        </Link>
        .
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <Button disabled={applying} onClick={apply}>
        Apply
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

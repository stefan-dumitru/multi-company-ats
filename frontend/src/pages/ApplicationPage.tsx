import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, ApiError, messageOf } from '@/api/client'
import { useResource } from '@/api/useResource'
import { useAuth } from '@/auth/AuthContext'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import RejectDialog from './application/RejectDialog'
import StageProgress from './application/StageProgress'
import { REJECTION_REASONS } from './application/types'
import type { ApplicationDetail, RejectionReason } from './application/types'
import { STAGE_BADGE } from './applications/types'
import type { ApplicationStage } from './applications/types'
import { STAFF_STAGE_LABELS } from './jobs/types'
import NotFoundPage from './NotFoundPage'

const VERSION_CONFLICT = 'version_conflict'
// Stages in which a decision can still be made (the server's rule, repeated to hide dead buttons).
const IN_PLAY: ApplicationStage[] = ['applied', 'screening', 'interview', 'offer']

/** One application, for the people hiring: who, where it stands, how it got there, and what to do. */
export default function ApplicationPage() {
  const { applicationId = '' } = useParams()
  const { state } = useAuth()
  // Only recruiters decide. Admins read; the server refuses anyone else's change anyway.
  const canDecide = state.status === 'authenticated' && state.user.role === 'recruiter'
  const application = useResource<ApplicationDetail>(`/api/applications/${applicationId}`)

  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [stale, setStale] = useState(false)
  const [rejecting, setRejecting] = useState(false)

  if (application.notFound) return <NotFoundPage />
  if (application.loading && !application.data) return <p role="status">Loading…</p>
  if (!application.data) {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-destructive">
          {application.error}
        </p>
        <Button variant="outline" size="sm" onClick={application.reload}>
          Try again
        </Button>
      </div>
    )
  }
  const current = application.data

  /**
   * Runs one change. Afterwards the page asks the server again, so it shows what is really there.
   * If someone else got there first, the page says so and waits: it does not guess.
   */
  async function change(request: () => Promise<unknown>) {
    setActionError('')
    setStale(false)
    setBusy(true)
    try {
      await request()
      application.reload()
    } catch (failure) {
      setActionError(messageOf(failure))
      setStale(failure instanceof ApiError && failure.code === VERSION_CONFLICT)
    } finally {
      setBusy(false)
      setRejecting(false)
    }
  }

  const advance = () =>
    change(() =>
      api(`/api/applications/${current.id}/advance`, {
        method: 'POST',
        body: { version: current.version },
      }),
    )

  const reject = (reason: RejectionReason, comment: string) =>
    change(() =>
      api(`/api/applications/${current.id}/reject`, {
        method: 'POST',
        body: { version: current.version, reason, comment: comment === '' ? null : comment },
      }),
    )

  const inPlay = IN_PLAY.includes(current.stage)

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Link
          to={`/manage/jobs/${current.job_id}`}
          className="text-sm text-primary underline underline-offset-4"
        >
          {current.job_title}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold break-words">{current.candidate_name}</h1>
          <Badge variant={STAGE_BADGE[current.stage]}>{STAFF_STAGE_LABELS[current.stage]}</Badge>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
          <span className="break-all">{current.candidate_email}</span>
          {current.candidate_phone && <span>{current.candidate_phone}</span>}
          {current.candidate_location && <span>{current.candidate_location}</span>}
        </div>
        <p className="text-sm text-muted-foreground">
          {`Applied ${formatDate(current.applied_at)}`}
        </p>
        {/* A new tab, so that if the download fails this page is not replaced by an error. */}
        <a
          href={`/api/applications/${current.id}/resume`}
          target="_blank"
          rel="noreferrer"
          className="text-sm text-primary underline underline-offset-4"
        >
          Download resume
        </a>
      </div>

      <StageProgress stage={current.stage} />

      {current.stage === 'withdrawn' && (
        <p className="text-muted-foreground">The candidate withdrew this application.</p>
      )}
      {current.rejection && (
        <section aria-labelledby="rejection-heading" className="space-y-1">
          <h2 id="rejection-heading" className="text-lg font-semibold">
            Rejection
          </h2>
          <p>{`Rejected from ${STAFF_STAGE_LABELS[current.rejection.from_stage]}.`}</p>
          <p>
            {REJECTION_REASONS.find((option) => option.value === current.rejection?.reason)
              ?.label ?? current.rejection.reason}
          </p>
          {current.rejection.comment && (
            <p className="whitespace-pre-wrap">{current.rejection.comment}</p>
          )}
          <p className="text-sm text-muted-foreground">
            Internal: the candidate is not shown the reason or the comment.
          </p>
        </section>
      )}

      {canDecide && inPlay && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3">
            {current.next_stage && (
              <Button disabled={busy} onClick={() => void advance()}>
                {`Move to ${STAFF_STAGE_LABELS[current.next_stage]}`}
              </Button>
            )}
            <Button variant="outline" disabled={busy} onClick={() => setRejecting(true)}>
              Reject
            </Button>
          </div>
        </div>
      )}
      {actionError && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {actionError}
          </p>
          {stale && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setActionError('')
                setStale(false)
                application.reload()
              }}
            >
              Reload
            </Button>
          )}
        </div>
      )}

      <section aria-labelledby="history-heading" className="space-y-3">
        <h2 id="history-heading" className="text-lg font-semibold">
          History
        </h2>
        <ol aria-label="History" className="space-y-2">
          {current.history.map((entry, index) => (
            <li key={index} className="rounded-lg border p-3">
              <p className="font-medium">
                {entry.from_stage
                  ? `${STAFF_STAGE_LABELS[entry.from_stage]} to ${STAFF_STAGE_LABELS[entry.to_stage]}`
                  : STAFF_STAGE_LABELS[entry.to_stage]}
              </p>
              <p className="text-sm text-muted-foreground">
                {`${entry.changed_by_name}, ${formatDate(entry.changed_at)}`}
              </p>
            </li>
          ))}
        </ol>
      </section>

      <RejectDialog
        open={rejecting}
        onOpenChange={setRejecting}
        candidateName={current.candidate_name}
        busy={busy}
        onReject={(reason, comment) => void reject(reason, comment)}
      />
    </div>
  )
}

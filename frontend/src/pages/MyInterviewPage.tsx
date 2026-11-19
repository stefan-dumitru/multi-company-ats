import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, ApiError, messageOf } from '@/api/client'
import { useResource } from '@/api/useResource'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDateTime } from '@/lib/format'
import ScorecardForm from './interviews/ScorecardForm'
import ScorecardView from './interviews/ScorecardView'
import { INTERVIEW_STATUS_LABELS } from './interviews/types'
import type { MyInterviewDetail, ScorecardSubmission } from './interviews/types'
import NotFoundPage from './NotFoundPage'

const ALREADY_SUBMITTED = 'scorecard_already_submitted'

/**
 * One interview for the interviewer assigned to it: the candidate, the resume, and the scorecard.
 * Blind scoring: colleagues' scorecards are shown only once the server says this interviewer has
 * submitted their own (`others_visible`); the screen never decides that for itself.
 */
export default function MyInterviewPage() {
  const { interviewId = '' } = useParams()
  const interview = useResource<MyInterviewDetail>(`/api/my/interviews/${interviewId}`)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  if (interview.notFound) return <NotFoundPage />
  if (interview.loading && !interview.data) return <p role="status">Loading…</p>
  if (!interview.data) {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-destructive">
          {interview.error}
        </p>
        <Button variant="outline" size="sm" onClick={interview.reload}>
          Try again
        </Button>
      </div>
    )
  }
  const current = interview.data

  async function submit(submission: ScorecardSubmission) {
    setError('')
    setSending(true)
    try {
      await api(`/api/my/interviews/${current.id}/scorecard`, {
        method: 'POST',
        body: submission,
      })
      interview.reload() // the server now includes the colleagues' scorecards
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === ALREADY_SUBMITTED) {
        // It got through already (another tab, or a retry): show what the server has.
        interview.reload()
      } else {
        setError(messageOf(failure)) // what was typed stays in the form
      }
    } finally {
      setSending(false)
    }
  }

  const scheduled = current.status === 'scheduled'
  const candidate = current.candidate

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Link to="/interviews" className="text-sm text-primary underline underline-offset-4">
          My interviews
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold break-words">{current.round_name}</h1>
          <Badge variant={scheduled ? 'default' : 'outline'}>
            {INTERVIEW_STATUS_LABELS[current.status]}
          </Badge>
        </div>
        <p>{formatDateTime(current.scheduled_at)}</p>
        <p className="text-sm text-muted-foreground">
          {`${current.job_title} · ${current.duration_minutes} minutes · ${current.location}`}
        </p>
      </div>

      {candidate && (
        <section aria-labelledby="candidate-heading" className="space-y-2">
          <h2 id="candidate-heading" className="text-lg font-semibold">
            Candidate
          </h2>
          <p className="font-medium break-words">{candidate.name}</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
            <span className="break-all">{candidate.email}</span>
            {candidate.phone && <span>{candidate.phone}</span>}
            {candidate.location && <span>{candidate.location}</span>}
          </div>
          {/* A new tab, so that if the download fails this page is not replaced by an error. */}
          <a
            href={`/api/my/interviews/${current.id}/resume`}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-primary underline underline-offset-4"
          >
            Download resume
          </a>
        </section>
      )}

      <section aria-labelledby="scorecard-heading" className="space-y-3">
        <h2 id="scorecard-heading" className="text-lg font-semibold">
          {current.my_scorecard ? 'Your scorecard' : 'Scorecard'}
        </h2>
        {current.my_scorecard && (
          <ul>
            <ScorecardView card={current.my_scorecard} />
          </ul>
        )}
        {!current.my_scorecard && scheduled && (
          <>
            <p className="text-sm text-muted-foreground">
              Your colleagues' scorecards stay hidden until after you submit yours, so nobody
              influences anybody.
            </p>
            <ScorecardForm busy={sending} error={error} onSubmit={(value) => void submit(value)} />
          </>
        )}
        {!current.my_scorecard && !scheduled && (
          <p className="text-muted-foreground">
            {current.status === 'cancelled'
              ? 'This interview was cancelled, so no scorecard can be submitted.'
              : 'This interview is closed, so no scorecard can be submitted.'}
          </p>
        )}
      </section>

      {current.others_visible && (
        <section aria-labelledby="colleagues-heading" className="space-y-3">
          <h2 id="colleagues-heading" className="text-lg font-semibold">
            Your colleagues' scorecards
          </h2>
          {current.others.length === 0 ? (
            <p className="text-muted-foreground">No colleague has submitted yet.</p>
          ) : (
            <ul className="space-y-3">
              {current.others.map((card) => (
                <ScorecardView key={card.id} card={card} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  )
}

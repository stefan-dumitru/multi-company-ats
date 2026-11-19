import { useState } from 'react'
import { api, ApiError, messageOf } from '@/api/client'
import { useResource } from '@/api/useResource'
import { Button } from '@/components/ui/button'
import type { ApplicationStage } from '../applications/types'
import InterviewCard from '../interviews/InterviewCard'
import InterviewForm from '../interviews/InterviewForm'
import type { Interview, InterviewChanges } from '../interviews/types'

const VERSION_CONFLICT = 'version_conflict'

interface InterviewsSectionProps {
  applicationId: string
  stage: ApplicationStage
  /** Recruiters schedule, reschedule and cancel; company admins only read. */
  canManage: boolean
}

/**
 * The interviews of one application and, for recruiters, the way to schedule more. Loads on its own,
 * so if it fails the rest of the page keeps working. If someone else changed an interview first, it
 * says so and waits for a reload: it does not guess.
 */
export default function InterviewsSection({
  applicationId,
  stage,
  canManage,
}: InterviewsSectionProps) {
  const interviews = useResource<Interview[]>(`/api/applications/${applicationId}/interviews`)
  // 'new' is the schedule form; an id is that interview's reschedule form.
  const [editing, setEditing] = useState<'new' | string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [stale, setStale] = useState(false)

  // Interviews can only be scheduled in the Interview stage; later, the ones held are still shown.
  const canSchedule = canManage && stage === 'interview'
  if (interviews.data && interviews.data.length === 0 && stage !== 'interview') return null

  /** Runs one change, then asks the server again so the screen shows what is really there. */
  async function change(request: () => Promise<unknown>, thenClose: boolean) {
    setActionError('')
    setStale(false)
    setBusy(true)
    try {
      await request()
      if (thenClose) setEditing(null)
      interviews.reload()
    } catch (failure) {
      setActionError(messageOf(failure))
      setStale(failure instanceof ApiError && failure.code === VERSION_CONFLICT)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="interviews-heading" className="space-y-3">
      <h2 id="interviews-heading" className="text-lg font-semibold">
        Interviews
      </h2>

      {interviews.loading && !interviews.data && <p role="status">Loading…</p>}
      {interviews.error && !interviews.data && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {interviews.error}
          </p>
          <Button variant="outline" size="sm" onClick={interviews.reload}>
            Try again
          </Button>
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
                setEditing(null)
                interviews.reload()
              }}
            >
              Reload
            </Button>
          )}
        </div>
      )}

      {interviews.data && interviews.data.length === 0 && (
        <p className="text-muted-foreground">No interviews scheduled yet.</p>
      )}
      {interviews.data && interviews.data.length > 0 && (
        <ul className="space-y-4">
          {interviews.data.map((interview) => (
            <InterviewCard
              key={interview.id}
              interview={interview}
              canManage={canManage}
              editing={editing === interview.id}
              busy={busy}
              onEdit={() => setEditing(interview.id)}
              onDiscard={() => setEditing(null)}
              onSave={(changes: InterviewChanges) => {
                if (Object.keys(changes).length === 0) return setEditing(null) // nothing to send
                void change(
                  () =>
                    api(`/api/interviews/${interview.id}`, {
                      method: 'PATCH',
                      body: { version: interview.version, ...changes },
                    }),
                  true,
                )
              }}
              onCancel={() =>
                void change(
                  () =>
                    api(`/api/interviews/${interview.id}/cancel`, {
                      method: 'POST',
                      body: { version: interview.version },
                    }),
                  false,
                )
              }
            />
          ))}
        </ul>
      )}

      {canSchedule && editing === 'new' && (
        <InterviewForm
          busy={busy}
          onDiscard={() => setEditing(null)}
          onSubmit={(changes) =>
            void change(
              () =>
                api(`/api/applications/${applicationId}/interviews`, {
                  method: 'POST',
                  body: changes,
                }),
              true,
            )
          }
        />
      )}
      {canSchedule && editing !== 'new' && (
        <Button disabled={busy} onClick={() => setEditing('new')}>
          Schedule an interview
        </Button>
      )}
    </section>
  )
}

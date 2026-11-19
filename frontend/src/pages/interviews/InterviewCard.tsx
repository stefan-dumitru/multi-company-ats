import { useState } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDateTime } from '@/lib/format'
import InterviewForm from './InterviewForm'
import ScorecardList from './ScorecardList'
import { INTERVIEW_STATUS_LABELS } from './types'
import type { Interview, InterviewChanges } from './types'

const CALENDAR_NOTES = {
  pending: 'Adding to the calendar…',
  synced: 'Calendar event created.',
  failed: 'Calendar sync failed. The interview itself is not affected.',
} as const

interface InterviewCardProps {
  interview: Interview
  /** Recruiters may reschedule and cancel; company admins only read. */
  canManage: boolean
  /** This card's reschedule form is open. */
  editing: boolean
  busy: boolean
  onEdit: () => void
  onDiscard: () => void
  onSave: (changes: InterviewChanges) => void
  onCancel: () => void
}

/** One interview with its people, its status and the scorecards submitted so far. */
export default function InterviewCard({
  interview,
  canManage,
  editing,
  busy,
  onEdit,
  onDiscard,
  onSave,
  onCancel,
}: InterviewCardProps) {
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const scheduled = interview.status === 'scheduled'
  const calendarNote =
    interview.calendar_sync_status === 'not_requested'
      ? null
      : CALENDAR_NOTES[interview.calendar_sync_status]

  return (
    <li className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h3 className="text-base font-semibold break-words">{interview.round_name}</h3>
          <p>{formatDateTime(interview.scheduled_at)}</p>
          <p className="text-sm text-muted-foreground">
            {`${interview.duration_minutes} minutes · ${interview.location}`}
          </p>
          <p className="text-sm">
            {'Interviewers: '}
            {interview.participants
              .map((person) =>
                person.is_active ? person.full_name : `${person.full_name} (deactivated)`,
              )
              .join(', ')}
          </p>
        </div>
        <Badge variant={scheduled ? 'default' : 'outline'}>
          {INTERVIEW_STATUS_LABELS[interview.status]}
        </Badge>
      </div>

      {interview.needs_reassignment && (
        <p className="text-sm text-destructive">
          This interview needs a new interviewer: someone assigned to it was deactivated.
        </p>
      )}
      {calendarNote && <p className="text-sm text-muted-foreground">{calendarNote}</p>}

      {canManage && scheduled && !editing && (
        <div className="flex flex-wrap gap-3">
          <Button variant="outline" disabled={busy} onClick={onEdit}>
            Reschedule
          </Button>
          <Button variant="outline" disabled={busy} onClick={() => setConfirmingCancel(true)}>
            Cancel interview
          </Button>
        </div>
      )}
      {editing && (
        <InterviewForm initial={interview} busy={busy} onSubmit={onSave} onDiscard={onDiscard} />
      )}

      <div className="space-y-2">
        <h4 className="text-sm font-medium">Scorecards</h4>
        <ScorecardList interviewId={interview.id} />
      </div>

      <AlertDialog open={confirmingCancel} onOpenChange={setConfirmingCancel}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel this interview?</AlertDialogTitle>
            <AlertDialogDescription>
              The interviewers and the candidate will be told it is cancelled. Scorecards already
              submitted stay.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep interview</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                onCancel()
                setConfirmingCancel(false)
              }}
            >
              Cancel interview
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  )
}

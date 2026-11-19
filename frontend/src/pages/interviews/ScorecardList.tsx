import { useResource } from '@/api/useResource'
import { Button } from '@/components/ui/button'
import ScorecardView from './ScorecardView'
import type { Scorecard } from './types'

/**
 * The scorecards submitted for one interview, as recruiters and admins read them: each one as soon
 * as it is in (blind scoring hides them from the other interviewers, not from staff). Loads on its
 * own. Feedback is typed by people: React shows it as text, and its line breaks are kept.
 */
export default function ScorecardList({ interviewId }: { interviewId: string }) {
  const scorecards = useResource<Scorecard[]>(`/api/interviews/${interviewId}/scorecards`)

  if (scorecards.loading && !scorecards.data) {
    return <p role="status">Loading scorecards…</p>
  }
  if (!scorecards.data) {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-destructive">
          {scorecards.error}
        </p>
        <Button variant="outline" size="sm" onClick={scorecards.reload}>
          Try again
        </Button>
      </div>
    )
  }
  if (scorecards.data.length === 0) {
    return <p className="text-sm text-muted-foreground">No scorecards submitted yet.</p>
  }
  return (
    <ul className="space-y-3">
      {scorecards.data.map((card) => (
        <ScorecardView key={card.id} card={card} />
      ))}
    </ul>
  )
}

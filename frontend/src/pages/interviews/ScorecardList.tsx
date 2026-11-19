import { useResource } from '@/api/useResource'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RECOMMENDATION_LABELS } from './types'
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
        <li key={card.id} className="space-y-1 rounded-md bg-muted/50 p-3">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{card.interviewer_name}</span>
            <Badge variant="secondary">{RECOMMENDATION_LABELS[card.recommendation]}</Badge>
          </p>
          <p className="text-sm text-muted-foreground">
            {`Overall ${card.overall_rating} · Technical ${card.technical_rating} · Communication ${card.communication_rating} · Problem solving ${card.problem_solving_rating} · Culture fit ${card.culture_fit_rating}`}
          </p>
          <p className="break-words whitespace-pre-wrap">{card.feedback}</p>
        </li>
      ))}
    </ul>
  )
}

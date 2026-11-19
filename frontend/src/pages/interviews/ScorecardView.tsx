import { Badge } from '@/components/ui/badge'
import { RECOMMENDATION_LABELS } from './types'
import type { Scorecard } from './types'

/** One submitted scorecard. Feedback is typed by people: React shows it as text, and its line
 *  breaks are kept. Used by the staff list and by the interviewer's own page. */
export default function ScorecardView({ card }: { card: Scorecard }) {
  return (
    <li className="space-y-1 rounded-md bg-muted/50 p-3">
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{card.interviewer_name}</span>
        <Badge variant="secondary">{RECOMMENDATION_LABELS[card.recommendation]}</Badge>
      </p>
      <p className="text-sm text-muted-foreground">
        {`Overall ${card.overall_rating} · Technical ${card.technical_rating} · Communication ${card.communication_rating} · Problem solving ${card.problem_solving_rating} · Culture fit ${card.culture_fit_rating}`}
      </p>
      <p className="break-words whitespace-pre-wrap">{card.feedback}</p>
    </li>
  )
}

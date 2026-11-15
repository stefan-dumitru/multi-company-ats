import { cn } from '@/lib/utils'
import { STAFF_STAGE_LABELS } from '../jobs/types'
import type { ApplicationStage } from '../applications/types'
import { PIPELINE } from './types'

/**
 * The line an application travels along. Rejected and withdrawn applications left it early, so
 * nothing on the line is marked current for them (the page says what happened instead).
 */
export default function StageProgress({ stage }: { stage: ApplicationStage }) {
  const position = PIPELINE.indexOf(stage)
  return (
    <ol aria-label="Progress" className="flex flex-wrap gap-2">
      {PIPELINE.map((step, index) => {
        const isCurrent = index === position
        return (
          <li
            key={step}
            aria-current={isCurrent ? 'step' : undefined}
            className={cn(
              'rounded-full border px-3 py-1 text-sm',
              isCurrent && 'border-primary bg-primary text-primary-foreground',
              position >= 0 && index < position && 'bg-muted text-foreground',
              (position < 0 || index > position) && 'text-muted-foreground',
            )}
          >
            {STAFF_STAGE_LABELS[step]}
          </li>
        )
      })}
    </ol>
  )
}

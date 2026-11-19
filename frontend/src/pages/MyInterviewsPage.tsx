import { useState } from 'react'
import { Link } from 'react-router'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import Pager from '@/components/Pager'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDateTime } from '@/lib/format'
import { INTERVIEW_STATUS_LABELS } from './interviews/types'
import type { MyInterviewRow } from './interviews/types'

const PAGE_SIZE = 20

type Which = 'awaiting' | 'upcoming' | 'all'

const FILTERS: { which: Which; label: string; empty: string }[] = [
  {
    which: 'awaiting',
    label: 'Awaiting my scorecard',
    empty: 'Nothing is waiting for your scorecard.',
  },
  { which: 'upcoming', label: 'Upcoming', empty: 'No upcoming interviews.' },
  {
    which: 'all',
    label: 'All my interviews',
    empty: 'You have not been assigned to any interview yet.',
  },
]

/** An interviewer's own interviews. Opens on what needs their scorecard. */
export default function MyInterviewsPage() {
  const [which, setWhich] = useState<Which>('awaiting')
  const [page, setPage] = useState(1)
  const interviews = useResource<Page<MyInterviewRow>>(
    `/api/my/interviews?filter=${which}&page=${page}&page_size=${PAGE_SIZE}`,
  )
  const current = FILTERS.find((filter) => filter.which === which)!

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">My interviews</h1>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((filter) => (
          <Button
            key={filter.which}
            variant={filter.which === which ? 'default' : 'outline'}
            aria-pressed={filter.which === which}
            onClick={() => {
              setWhich(filter.which)
              setPage(1)
            }}
          >
            {filter.label}
          </Button>
        ))}
      </div>

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
      {interviews.data && interviews.data.total === 0 && (
        <p className="text-muted-foreground">{current.empty}</p>
      )}
      {interviews.data && interviews.data.total > 0 && interviews.data.items.length === 0 && (
        // Rows went away while this page was open, so this page no longer exists.
        <div className="space-y-2">
          <p className="text-muted-foreground">There are no interviews on this page any more.</p>
          <Button variant="outline" size="sm" onClick={() => setPage(1)}>
            Back to the first page
          </Button>
        </div>
      )}
      {interviews.data && interviews.data.items.length > 0 && (
        <>
          <ul className="space-y-4">
            {interviews.data.items.map((interview) => (
              <li key={interview.id} className="space-y-2 rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 space-y-1">
                    <h2 className="text-lg font-semibold break-words">
                      <Link
                        to={`/interviews/${interview.id}`}
                        className="underline-offset-4 hover:underline"
                      >
                        {interview.round_name}
                      </Link>
                    </h2>
                    <p>{formatDateTime(interview.scheduled_at)}</p>
                    <p className="text-sm text-muted-foreground">
                      {`${interview.job_title}${interview.candidate_name ? ` · ${interview.candidate_name}` : ''} · ${interview.duration_minutes} minutes`}
                    </p>
                  </div>
                  <Badge variant={interview.status === 'scheduled' ? 'default' : 'outline'}>
                    {INTERVIEW_STATUS_LABELS[interview.status]}
                  </Badge>
                </div>
                {interview.status !== 'cancelled' && (
                  <p className="text-sm">
                    {interview.my_scorecard_submitted ? 'Scorecard submitted' : 'Scorecard needed'}
                  </p>
                )}
              </li>
            ))}
          </ul>
          <Pager
            page={interviews.data.page}
            pageSize={interviews.data.page_size}
            total={interviews.data.total}
            onChange={setPage}
          />
        </>
      )}
    </div>
  )
}

import { useState } from 'react'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import Pager from '@/components/Pager'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import { STAGE_BADGE } from '../applications/types'
import { STAFF_STAGE_LABELS } from './types'
import type { Applicant } from './types'

const PAGE_SIZE = 20

/**
 * Who applied to this job, with each person's resume. Loads on its own, so if it fails the rest of
 * the job page keeps working. Names and emails are typed by candidates: React shows them as text.
 */
export default function ApplicantsSection({ jobId }: { jobId: string }) {
  const [page, setPage] = useState(1)
  const applicants = useResource<Page<Applicant>>(
    `/api/jobs/${jobId}/applications?page=${page}&page_size=${PAGE_SIZE}`,
  )

  return (
    <section aria-labelledby="applicants-heading" className="space-y-3">
      <h2 id="applicants-heading" className="text-lg font-semibold">
        Applicants
      </h2>
      {applicants.loading && !applicants.data && <p role="status">Loading…</p>}
      {applicants.error && !applicants.data && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {applicants.error}
          </p>
          <Button variant="outline" size="sm" onClick={applicants.reload}>
            Try again
          </Button>
        </div>
      )}
      {applicants.data && applicants.data.total === 0 && (
        <p className="text-muted-foreground">No one has applied yet.</p>
      )}
      {applicants.data && applicants.data.total > 0 && applicants.data.items.length === 0 && (
        // Rows went away while this page was open, so this page no longer exists.
        <div className="space-y-2">
          <p className="text-muted-foreground">There are no applicants on this page any more.</p>
          <Button variant="outline" size="sm" onClick={() => setPage(1)}>
            Back to the first page
          </Button>
        </div>
      )}
      {applicants.data && applicants.data.items.length > 0 && (
        <>
          <ul className="space-y-3">
            {applicants.data.items.map((applicant) => (
              <li key={applicant.id} className="space-y-2 rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 space-y-1">
                    <p className="font-medium break-words">{applicant.candidate_name}</p>
                    <p className="text-sm break-all text-muted-foreground">
                      {applicant.candidate_email}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {`Applied ${formatDate(applicant.applied_at)}`}
                    </p>
                  </div>
                  <Badge variant={STAGE_BADGE[applicant.stage]}>
                    {STAFF_STAGE_LABELS[applicant.stage]}
                  </Badge>
                </div>
                {/* A new tab, so that if the download fails this page is not replaced by an error. */}
                <a
                  href={`/api/applications/${applicant.id}/resume`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-primary underline underline-offset-4"
                >
                  Download resume
                </a>
              </li>
            ))}
          </ul>
          <Pager
            page={applicants.data.page}
            pageSize={applicants.data.page_size}
            total={applicants.data.total}
            onChange={setPage}
          />
        </>
      )}
    </section>
  )
}

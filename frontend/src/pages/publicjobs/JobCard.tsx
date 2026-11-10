import { Link } from 'react-router'
import { formatDate } from '@/lib/format'
import type { PublicJobSummary } from './types'

export default function JobCard({ job }: { job: PublicJobSummary }) {
  const headingId = `public-job-${job.id}`
  return (
    <article aria-labelledby={headingId} className="space-y-2 rounded-md border p-4">
      <h2 id={headingId} className="text-lg font-semibold">
        <Link to={`/jobs/${job.id}`} className="text-primary underline-offset-4 hover:underline">
          {job.title}
        </Link>
      </h2>
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{job.company_name}</span>
        {' · '}
        <span>
          {job.department_name} · {job.location}
        </span>
        {job.opened_at && (
          <>
            {' · '}
            <span>{formatDate(job.opened_at)}</span>
          </>
        )}
      </p>
      <p className="text-sm">{job.excerpt}</p>
    </article>
  )
}

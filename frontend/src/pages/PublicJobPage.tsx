import { Link, useParams } from 'react-router'
import { useResource } from '@/api/useResource'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import type { PublicJob } from './publicjobs/types'

/** One open job, for anyone. */
export default function PublicJobPage() {
  const { jobId = '' } = useParams()
  const job = useResource<PublicJob>(`/api/public/jobs/${jobId}`)

  if (job.notFound) {
    // Jobs that fill up or close disappear, so a saved link can lead here: say that kindly.
    return (
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold">This job is no longer available</h1>
        <p className="text-muted-foreground">It may have been filled, or the link may be wrong.</p>
        <Link to="/jobs" className="text-primary underline underline-offset-4">
          See other open jobs
        </Link>
      </section>
    )
  }
  if (job.loading && !job.data) return <p role="status">Loading…</p>
  if (!job.data) {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-destructive">
          {job.error}
        </p>
        <Button variant="outline" size="sm" onClick={job.reload}>
          Try again
        </Button>
      </div>
    )
  }
  const current = job.data

  return (
    <article className="max-w-3xl space-y-6">
      <Link to="/jobs" className="text-sm text-primary underline underline-offset-4">
        All jobs
      </Link>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{current.title}</h1>
        <p className="flex flex-wrap gap-x-3 text-muted-foreground">
          <span className="font-medium text-foreground">{current.company_name}</span>
          <span>{current.department_name}</span>
          <span>{current.location}</span>
          {current.opened_at && <span>{formatDate(current.opened_at)}</span>}
        </p>
        <Link
          to={`/jobs?company_id=${encodeURIComponent(current.company_id)}`}
          className="text-sm text-primary underline underline-offset-4"
        >
          More jobs at {current.company_name}
        </Link>
      </header>
      {/* pre-wrap keeps the paragraphs the recruiter typed. The text is shown as text, not HTML. */}
      <p className="whitespace-pre-wrap">{current.description}</p>
    </article>
  )
}

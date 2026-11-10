import { useSearchParams } from 'react-router'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import Pager from '@/components/Pager'
import { Button } from '@/components/ui/button'
import JobCard from './publicjobs/JobCard'
import SearchForm from './publicjobs/SearchForm'
import type { PublicJobSummary } from './publicjobs/types'

const PAGE_SIZE = 20
// The server refuses pages beyond this; asking for one would only show an error.
const MAX_PAGE = 10_000

/** The page number in the address, or 1 when it is missing or makes no sense. */
function pageFrom(text: string | null): number {
  const page = Number.parseInt(text ?? '', 10)
  return Number.isFinite(page) && page >= 1 && page <= MAX_PAGE ? page : 1
}

/**
 * The public job search. What was asked for lives in the address (`?q=...&location=...&page=2`),
 * so the back button works and a search can be shared as a link.
 */
export default function PublicJobsPage() {
  const [params, setParams] = useSearchParams()
  const keywords = params.get('q') ?? ''
  const location = params.get('location') ?? ''
  const companyId = params.get('company_id') ?? ''
  const page = pageFrom(params.get('page'))

  const request = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (keywords.trim()) request.set('q', keywords.trim())
  if (location.trim()) request.set('location', location.trim())
  if (companyId) request.set('company_id', companyId)
  const jobs = useResource<Page<PublicJobSummary>>(`/api/public/jobs?${request.toString()}`)

  /** Change some of what is asked for; anything not mentioned stays. Always from page 1. */
  function update(changes: Record<string, string>) {
    const next = new URLSearchParams(params)
    next.delete('page')
    for (const [name, value] of Object.entries(changes)) {
      if (value) next.set(name, value)
      else next.delete(name)
    }
    setParams(next)
  }

  function goToPage(newPage: number) {
    const next = new URLSearchParams(params)
    if (newPage > 1) next.set('page', String(newPage))
    else next.delete('page')
    setParams(next)
  }

  const searching = keywords.trim() !== '' || location.trim() !== ''
  const found = jobs.data
  const companyName = found?.items[0]?.company_name

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Find a job</h1>

      <SearchForm
        key={`${keywords}|${location}`}
        keywords={keywords}
        location={location}
        onSearch={(newKeywords, newLocation) => update({ q: newKeywords, location: newLocation })}
      />

      {companyId && (
        <p className="flex flex-wrap items-center gap-3 text-sm">
          <span>Jobs at {companyName ?? 'one company'}</span>
          <Button variant="outline" size="sm" onClick={() => update({ company_id: '' })}>
            Show all companies
          </Button>
        </p>
      )}

      {jobs.loading && <p role="status">Loading…</p>}
      {jobs.error && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {jobs.error}
          </p>
          <Button variant="outline" size="sm" onClick={jobs.reload}>
            Try again
          </Button>
        </div>
      )}

      {found && found.total === 0 && searching && (
        <div className="space-y-2">
          <p className="text-muted-foreground">No jobs match your search.</p>
          <Button variant="outline" size="sm" onClick={() => update({ q: '', location: '' })}>
            Clear search
          </Button>
        </div>
      )}
      {found && found.total === 0 && !searching && (
        <p className="text-muted-foreground">
          {companyId
            ? 'This company has no open jobs right now.'
            : 'There are no open jobs right now. Please check back soon.'}
        </p>
      )}
      {found && found.items.length > 0 && (
        <>
          <p role="status" className="text-sm text-muted-foreground">
            {found.total} {found.total === 1 ? 'job' : 'jobs'} found
          </p>
          <div className="space-y-4">
            {found.items.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>
          <Pager page={page} pageSize={PAGE_SIZE} total={found.total} onChange={goToPage} />
        </>
      )}
    </div>
  )
}

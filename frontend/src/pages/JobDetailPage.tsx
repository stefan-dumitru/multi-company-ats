import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, ApiError, messageOf } from '@/api/client'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import { useAuth } from '@/auth/AuthContext'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import JobActions from './jobs/JobActions'
import JobForm from './jobs/JobForm'
import type { JobFormValues } from './jobs/JobForm'
import RecruitersPanel from './jobs/RecruitersPanel'
import { STATUS_LABELS } from './jobs/types'
import type { DepartmentChoice, JobDetail, Recruiter } from './jobs/types'
import NotFoundPage from './NotFoundPage'

const VERSION_CONFLICT = 'version_conflict'

export default function JobDetailPage() {
  const { jobId = '' } = useParams()
  const { state } = useAuth()
  const navigate = useNavigate()
  const currentUserId = state.status === 'authenticated' ? state.user.id : ''

  const job = useResource<JobDetail>(`/api/jobs/${jobId}`)
  // Departments a job may be moved to; the job's own (possibly archived) one is added below.
  const departments = useResource<Page<DepartmentChoice>>('/api/departments?page_size=100')
  const companyRecruiters = useResource<Page<Recruiter>>('/api/recruiters?page_size=100')

  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [saved, setSaved] = useState(false)
  // After a version conflict the form offers "load the latest version"; counting resets lets it
  // start again from what the server has.
  const [conflict, setConflict] = useState(false)
  const [formResets, setFormResets] = useState(0)

  if (job.notFound) return <NotFoundPage />
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

  /**
   * Runs one change to the job. Afterwards the page reloads, so it always shows what the server
   * has, also after a refusal (for example "changed by someone else"). A change that ends the
   * page, such as deleting the draft, supplies `thenLeave` instead.
   */
  async function change(request: () => Promise<unknown>, thenLeave?: () => void) {
    setActionError('')
    setSaved(false)
    setBusy(true)
    try {
      await request()
      if (thenLeave) {
        thenLeave()
        return
      }
    } catch (failure) {
      setActionError(messageOf(failure))
    } finally {
      setBusy(false)
    }
    job.reload()
  }

  async function saveChanges(values: JobFormValues) {
    setSaved(false)
    setConflict(false)
    try {
      await api(`/api/jobs/${current.id}`, {
        method: 'PATCH',
        body: { version: current.version, ...values },
      })
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === VERSION_CONFLICT) setConflict(true)
      throw failure // the form shows the message and keeps what was typed
    }
    setSaved(true)
    job.reload()
  }

  const departmentChoices = [...(departments.data?.items ?? [])]
  if (!departmentChoices.some((choice) => choice.id === current.department.id)) {
    // The job keeps working in a department that was archived after it was chosen.
    departmentChoices.unshift({
      ...current.department,
      name: current.department.is_archived
        ? `${current.department.name} (archived)`
        : current.department.name,
    })
  }

  const post = (action: string) =>
    api(`/api/jobs/${current.id}/${action}`, { method: 'POST', body: { version: current.version } })

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Link to="/manage/jobs" className="text-sm text-primary underline underline-offset-4">
          Back to jobs
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{current.title}</h1>
          <Badge variant={current.status === 'open' ? 'default' : 'secondary'}>
            {STATUS_LABELS[current.status]}
          </Badge>
        </div>
        {current.opened_at && (
          <p className="text-sm text-muted-foreground">
            Opened <span>{formatDate(current.opened_at)}</span>
          </p>
        )}
        {current.needs_reassignment && (
          <p className="text-sm text-destructive">
            This job has no active recruiter. Add one below before publishing.
          </p>
        )}
      </div>

      <div className="space-y-3">
        <JobActions
          status={current.status}
          busy={busy}
          onPublish={() => void change(() => post('publish'))}
          onClose={() => void change(() => post('close'))}
          onDeleteDraft={() =>
            void change(
              () => api(`/api/jobs/${current.id}`, { method: 'DELETE' }),
              () => navigate('/manage/jobs'),
            )
          }
        />
        {actionError && (
          <p role="alert" className="text-sm text-destructive">
            {actionError}
          </p>
        )}
      </div>

      <section aria-labelledby="details-heading" className="space-y-4">
        <h2 id="details-heading" className="text-lg font-semibold">
          Details
        </h2>
        {current.status === 'closed' ? (
          <dl className="max-w-2xl space-y-3">
            <div>
              <dt className="text-sm text-muted-foreground">Department</dt>
              <dd>{current.department.name}</dd>
            </div>
            <div>
              <dt className="text-sm text-muted-foreground">Location</dt>
              <dd>{current.location}</dd>
            </div>
            {current.closed_at && (
              <div>
                <dt className="text-sm text-muted-foreground">Closed on</dt>
                <dd>{formatDate(current.closed_at)}</dd>
              </div>
            )}
            <div>
              <dt className="text-sm text-muted-foreground">Description</dt>
              <dd className="whitespace-pre-wrap">{current.description}</dd>
            </div>
          </dl>
        ) : (
          <>
            <JobForm
              // A new version, or "load the latest", starts the form again from the server's values.
              key={`${current.version}-${formResets}`}
              departments={departmentChoices}
              initial={{
                title: current.title,
                location: current.location,
                department_id: current.department.id,
                description: current.description,
              }}
              submitLabel="Save changes"
              onSubmit={saveChanges}
            />
            {saved && <p role="status">Changes saved.</p>}
            {conflict && (
              <Button
                variant="outline"
                onClick={() => {
                  setConflict(false)
                  setFormResets((count) => count + 1)
                  job.reload()
                }}
              >
                Load the latest version
              </Button>
            )}
          </>
        )}
      </section>

      <RecruitersPanel
        recruiters={current.recruiters}
        companyRecruiters={companyRecruiters.data?.items ?? null}
        companyRecruitersError={companyRecruiters.error}
        onRetryCompanyRecruiters={companyRecruiters.reload}
        currentUserId={currentUserId}
        busy={busy}
        onAdd={(person) =>
          void change(() =>
            api(`/api/jobs/${current.id}/recruiters`, {
              method: 'POST',
              body: { user_id: person.id },
            }),
          )
        }
        onRemove={(person) => {
          const removedMyself =
            person.id === currentUserId &&
            state.status === 'authenticated' &&
            state.user.role === 'recruiter'
          void change(
            () => api(`/api/jobs/${current.id}/recruiters/${person.id}`, { method: 'DELETE' }),
            // A recruiter who leaves a job can no longer see it, so its page would only say "not found".
            removedMyself ? () => navigate('/manage/jobs') : undefined,
          )
        }}
      />
    </div>
  )
}

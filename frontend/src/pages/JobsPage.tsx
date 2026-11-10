import { useState } from 'react'
import { Link } from 'react-router'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import { useAuth } from '@/auth/AuthContext'
import Pager from '@/components/Pager'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import JobsTable from './jobs/JobsTable'
import { STATUS_LABELS } from './jobs/types'
import type { DepartmentChoice, JobStatus, JobSummary } from './jobs/types'

const PAGE_SIZE = 20

export default function JobsPage() {
  const { state } = useAuth()
  const isAdmin = state.status === 'authenticated' && state.user.role === 'company_admin'
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<JobStatus | ''>('')
  const [departmentId, setDepartmentId] = useState('')

  // For the department filter: archived ones too, since old jobs may still sit in them.
  const departments = useResource<Page<DepartmentChoice>>(
    '/api/departments?include_archived=true&page_size=100',
  )
  const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (status) query.set('status', status)
  if (departmentId) query.set('department_id', departmentId)
  const jobs = useResource<Page<JobSummary>>(`/api/jobs?${query.toString()}`)

  const filtered = status !== '' || departmentId !== ''

  // A filter change always starts again from the first page: the old page number may not exist.
  function changeStatus(value: string) {
    setStatus(value as JobStatus | '')
    setPage(1)
  }
  function changeDepartment(value: string) {
    setDepartmentId(value)
    setPage(1)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{isAdmin ? 'Jobs' : 'My jobs'}</h1>
        <Button asChild>
          <Link to="/manage/jobs/new">New job</Link>
        </Button>
      </div>
      {!isAdmin && (
        <p className="text-sm text-muted-foreground">
          These are the jobs assigned to you. An admin or a colleague on a job can add you to it.
        </p>
      )}

      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-2">
          <Label htmlFor="filter-status">Status</Label>
          <NativeSelect
            id="filter-status"
            value={status}
            onChange={(event) => changeStatus(event.target.value)}
          >
            <NativeSelectOption value="">All</NativeSelectOption>
            {(Object.keys(STATUS_LABELS) as JobStatus[]).map((option) => (
              <NativeSelectOption key={option} value={option}>
                {STATUS_LABELS[option]}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-2">
          <Label htmlFor="filter-department">Department</Label>
          <NativeSelect
            id="filter-department"
            value={departmentId}
            onChange={(event) => changeDepartment(event.target.value)}
          >
            <NativeSelectOption value="">All</NativeSelectOption>
            {departments.data?.items.map((department) => (
              <NativeSelectOption key={department.id} value={department.id}>
                {department.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
      </div>

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
      {jobs.data && jobs.data.items.length === 0 && (
        <p className="text-muted-foreground">
          {filtered
            ? 'No jobs match these filters.'
            : isAdmin
              ? 'No jobs yet. Create the first one.'
              : 'No jobs assigned to you yet.'}
        </p>
      )}
      {jobs.data && jobs.data.items.length > 0 && (
        <>
          <JobsTable jobs={jobs.data.items} />
          <Pager page={page} pageSize={PAGE_SIZE} total={jobs.data.total} onChange={setPage} />
        </>
      )}
    </div>
  )
}

import { Link, useNavigate } from 'react-router'
import { api } from '@/api/client'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import { useAuth } from '@/auth/AuthContext'
import { Button } from '@/components/ui/button'
import JobForm from './jobs/JobForm'
import type { JobFormValues } from './jobs/JobForm'
import type { DepartmentChoice } from './jobs/types'

export default function NewJobPage() {
  const { state } = useAuth()
  const isAdmin = state.status === 'authenticated' && state.user.role === 'company_admin'
  const navigate = useNavigate()
  // Only departments a new job may use: the server leaves archived ones out by default.
  const departments = useResource<Page<DepartmentChoice>>('/api/departments?page_size=100')

  async function createJob(values: JobFormValues) {
    await api('/api/jobs', { method: 'POST', body: values })
    navigate('/manage/jobs')
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">New job</h1>
      {departments.loading && <p role="status">Loading…</p>}
      {departments.error && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {departments.error}
          </p>
          <Button variant="outline" size="sm" onClick={departments.reload}>
            Try again
          </Button>
        </div>
      )}
      {departments.data && departments.data.items.length === 0 && (
        <p className="text-muted-foreground">
          There are no departments yet, and every job belongs to one.{' '}
          {isAdmin ? (
            <Link to="/departments" className="text-primary underline underline-offset-4">
              Add a department
            </Link>
          ) : (
            'Ask a company admin to add one.'
          )}
        </p>
      )}
      {departments.data && departments.data.items.length > 0 && (
        <JobForm
          departments={departments.data.items}
          submitLabel="Create job"
          onSubmit={createJob}
        />
      )}
    </div>
  )
}

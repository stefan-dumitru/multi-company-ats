import { useState } from 'react'
import { api, messageOf } from '@/api/client'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import Pager from '@/components/Pager'
import { Button } from '@/components/ui/button'
import AddDepartmentForm from './departments/AddDepartmentForm'
import DepartmentsTable from './departments/DepartmentsTable'
import type { Department } from './departments/types'

const PAGE_SIZE = 20

export default function DepartmentsPage() {
  const [page, setPage] = useState(1)
  // Archived departments are listed too: this is where an admin brings one back.
  const departments = useResource<Page<Department>>(
    `/api/departments?include_archived=true&page=${page}&page_size=${PAGE_SIZE}`,
  )
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')

  async function add(name: string) {
    await api('/api/departments', { method: 'POST', body: { name } })
    departments.reload()
  }

  async function rename(department: Department, name: string) {
    setBusyId(department.id)
    try {
      await api(`/api/departments/${department.id}`, { method: 'PATCH', body: { name } })
      departments.reload()
    } finally {
      setBusyId(null)
    }
  }

  /** Runs a change to one department, then reloads so the screen shows what the server has. */
  async function change(
    department: Department,
    request: () => Promise<unknown>,
    afterSuccess?: () => void,
  ) {
    setActionError('')
    setBusyId(department.id)
    try {
      await request()
      afterSuccess?.()
    } catch (failure) {
      setActionError(messageOf(failure))
    } finally {
      setBusyId(null)
      departments.reload()
    }
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Departments</h1>

      <section className="space-y-3" aria-labelledby="add-heading">
        <h2 id="add-heading" className="text-lg font-semibold">
          Add a department
        </h2>
        <AddDepartmentForm onAdd={add} />
      </section>

      <section className="space-y-3" aria-labelledby="list-heading">
        <h2 id="list-heading" className="text-lg font-semibold">
          All departments
        </h2>
        {actionError && (
          <p role="alert" className="text-sm text-destructive">
            {actionError}
          </p>
        )}
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
        {departments.data && departments.data.total === 0 && (
          <p className="text-muted-foreground">
            No departments yet. Add one above before creating jobs.
          </p>
        )}
        {departments.data && departments.data.total > 0 && departments.data.items.length === 0 && (
          // Someone else deleted rows while this page was open, so this page no longer exists.
          <div className="space-y-2">
            <p className="text-muted-foreground">There are no departments on this page any more.</p>
            <Button variant="outline" size="sm" onClick={() => setPage(1)}>
              Back to the first page
            </Button>
          </div>
        )}
        {departments.data && departments.data.items.length > 0 && (
          <>
            <DepartmentsTable
              departments={departments.data.items}
              busyId={busyId}
              onRename={rename}
              onSetArchived={(department, archived) =>
                void change(department, () =>
                  api(`/api/departments/${department.id}/${archived ? 'archive' : 'unarchive'}`, {
                    method: 'POST',
                  }),
                )
              }
              onDelete={(department) => {
                // Deleting the only row on a later page would leave that page empty: go back one.
                const wasOnlyRowOnPage = page > 1 && departments.data?.items.length === 1
                void change(
                  department,
                  () => api(`/api/departments/${department.id}`, { method: 'DELETE' }),
                  () => {
                    if (wasOnlyRowOnPage) setPage(page - 1)
                  },
                )
              }}
            />
            <Pager
              page={page}
              pageSize={PAGE_SIZE}
              total={departments.data.total}
              onChange={setPage}
            />
          </>
        )}
      </section>
    </div>
  )
}

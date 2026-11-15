import { useState } from 'react'
import { Link } from 'react-router'
import { api, messageOf } from '@/api/client'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import Pager from '@/components/Pager'
import { Button } from '@/components/ui/button'
import ApplicationCard from './applications/ApplicationCard'
import type { MyApplication } from './applications/types'

const PAGE_SIZE = 20

/** The candidate's own applications, with withdraw and reactivate. */
export default function ApplicationsPage() {
  const [page, setPage] = useState(1)
  const applications = useResource<Page<MyApplication>>(
    `/api/applications?page=${page}&page_size=${PAGE_SIZE}`,
  )
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')

  /** Runs one change, then reloads so the screen shows what the server now has. */
  async function change(application: MyApplication, action: 'withdraw' | 'reactivate') {
    setActionError('')
    setBusyId(application.id)
    try {
      await api(`/api/applications/${application.id}/${action}`, { method: 'POST' })
    } catch (failure) {
      setActionError(messageOf(failure))
    } finally {
      setBusyId(null)
      applications.reload()
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">My applications</h1>
      {actionError && (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      )}
      {applications.loading && !applications.data && <p role="status">Loading…</p>}
      {applications.error && !applications.data && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {applications.error}
          </p>
          <Button variant="outline" size="sm" onClick={applications.reload}>
            Try again
          </Button>
        </div>
      )}
      {applications.data && applications.data.total === 0 && (
        <div className="space-y-2">
          <p className="text-muted-foreground">You have not applied to anything yet.</p>
          <Link to="/jobs" className="text-primary underline underline-offset-4">
            Find a job
          </Link>
        </div>
      )}
      {applications.data && applications.data.total > 0 && applications.data.items.length === 0 && (
        // Rows went away while this page was open, so this page no longer exists.
        <div className="space-y-2">
          <p className="text-muted-foreground">There are no applications on this page any more.</p>
          <Button variant="outline" size="sm" onClick={() => setPage(1)}>
            Back to the first page
          </Button>
        </div>
      )}
      {applications.data && applications.data.items.length > 0 && (
        <>
          <ul className="space-y-4">
            {applications.data.items.map((application) => (
              <ApplicationCard
                key={application.id}
                application={application}
                busy={busyId === application.id}
                onWithdraw={() => void change(application, 'withdraw')}
                onReactivate={() => void change(application, 'reactivate')}
              />
            ))}
          </ul>
          <Pager
            page={applications.data.page}
            pageSize={applications.data.page_size}
            total={applications.data.total}
            onChange={setPage}
          />
        </>
      )}
    </div>
  )
}

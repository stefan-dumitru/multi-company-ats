import { useState } from 'react'
import { Link } from 'react-router'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import { STAGE_BADGE, STAGE_LABELS, WITHDRAWABLE } from './types'
import type { MyApplication } from './types'

interface ApplicationCardProps {
  application: MyApplication
  /** A request for this application is running; its buttons are switched off meanwhile. */
  busy: boolean
  onWithdraw: () => void
  onReactivate: () => void
}

/**
 * One application as a card rather than a table row: it stacks, so it reads the same at phone
 * width and on a desktop.
 */
export default function ApplicationCard({
  application,
  busy,
  onWithdraw,
  onReactivate,
}: ApplicationCardProps) {
  const [confirmingWithdraw, setConfirmingWithdraw] = useState(false)

  return (
    <li className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h2 className="text-lg font-semibold break-words">
            {/* A closed job's page is gone, so there is nothing to link to. */}
            {application.job_is_open ? (
              <Link
                to={`/jobs/${application.job_id}`}
                className="underline-offset-4 hover:underline"
              >
                {application.job_title}
              </Link>
            ) : (
              application.job_title
            )}
          </h2>
          <p className="text-muted-foreground">{application.company_name}</p>
          <p className="text-sm text-muted-foreground">
            {`Applied ${formatDate(application.applied_at)}`}
          </p>
        </div>
        <Badge variant={STAGE_BADGE[application.stage]}>{STAGE_LABELS[application.stage]}</Badge>
      </div>

      {WITHDRAWABLE.includes(application.stage) && (
        <Button variant="outline" disabled={busy} onClick={() => setConfirmingWithdraw(true)}>
          Withdraw
        </Button>
      )}
      {application.stage === 'withdrawn' && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            disabled={busy || !application.job_is_open}
            onClick={onReactivate}
          >
            Reactivate
          </Button>
          {!application.job_is_open && (
            <span className="text-sm text-muted-foreground">This job is closed.</span>
          )}
        </div>
      )}

      <AlertDialog open={confirmingWithdraw} onOpenChange={setConfirmingWithdraw}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Withdraw this application?</AlertDialogTitle>
            <AlertDialogDescription>
              {`${application.company_name} will no longer consider you for ${application.job_title}. `}
              You can reactivate it later while the job is still open.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                onWithdraw()
                setConfirmingWithdraw(false)
              }}
            >
              Withdraw
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  )
}

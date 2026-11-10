import { useState } from 'react'
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
import { Button } from '@/components/ui/button'
import type { JobStatus } from './types'

interface JobActionsProps {
  status: JobStatus
  /** A request is running; the buttons are switched off meanwhile. */
  busy: boolean
  onPublish: () => void
  onClose: () => void
  onDeleteDraft: () => void
}

type Confirming = 'close' | 'delete' | null

/** The buttons that move a job along: publish a draft, close an open job, delete a draft. */
export default function JobActions({
  status,
  busy,
  onPublish,
  onClose,
  onDeleteDraft,
}: JobActionsProps) {
  const [confirming, setConfirming] = useState<Confirming>(null)

  if (status === 'closed') {
    return (
      <p className="text-sm text-muted-foreground">This job is closed and cannot be changed.</p>
    )
  }

  return (
    <>
      <div className="flex flex-wrap gap-3">
        {status === 'draft' && (
          <>
            <Button disabled={busy} onClick={onPublish}>
              Publish
            </Button>
            <Button variant="outline" disabled={busy} onClick={() => setConfirming('delete')}>
              Delete draft
            </Button>
          </>
        )}
        {status === 'open' && (
          <Button variant="outline" disabled={busy} onClick={() => setConfirming('close')}>
            Close job
          </Button>
        )}
      </div>

      <AlertDialog
        open={confirming !== null}
        onOpenChange={(open) => {
          if (!open) setConfirming(null)
        }}
      >
        <AlertDialogContent>
          {confirming === 'close' ? (
            <AlertDialogHeader>
              <AlertDialogTitle>Close this job?</AlertDialogTitle>
              <AlertDialogDescription>
                Candidates will no longer see it or be able to apply. Applications already received
                are kept. A closed job cannot be reopened.
              </AlertDialogDescription>
            </AlertDialogHeader>
          ) : (
            <AlertDialogHeader>
              <AlertDialogTitle>Delete this draft?</AlertDialogTitle>
              <AlertDialogDescription>
                The draft is removed for good. Nobody has seen it yet.
              </AlertDialogDescription>
            </AlertDialogHeader>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (confirming === 'close') onClose()
                if (confirming === 'delete') onDeleteDraft()
                setConfirming(null)
              }}
            >
              {confirming === 'close' ? 'Close job' : 'Delete draft'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

import { useState } from 'react'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Textarea } from '@/components/ui/textarea'
import { MAX_COMMENT_LENGTH, REJECTION_REASONS } from './types'
import type { RejectionReason } from './types'

interface RejectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  candidateName: string
  /** A request is running; the form is switched off meanwhile. */
  busy: boolean
  onReject: (reason: RejectionReason, comment: string) => void
}

/** Asks for the reason (and a comment) before a rejection is sent. */
export default function RejectDialog({
  open,
  onOpenChange,
  candidateName,
  busy,
  onReject,
}: RejectDialogProps) {
  const [reason, setReason] = useState<RejectionReason | ''>('')
  const [comment, setComment] = useState('')
  const [problem, setProblem] = useState('')

  function submit() {
    // The server checks all of this too; here it only saves a round trip.
    if (reason === '') {
      setProblem('Please pick a reason from the list.')
      return
    }
    if (reason === 'other' && comment.trim() === '') {
      setProblem('A comment is required when the reason is "other".')
      return
    }
    setProblem('')
    onReject(reason, comment.trim())
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setReason('')
          setComment('')
          setProblem('')
        }
        onOpenChange(next)
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Reject this application?</AlertDialogTitle>
          <AlertDialogDescription>
            {`${candidateName} will be told, kindly, that the company will not continue. The reason and your comment stay internal. A rejection cannot be undone.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="rejection-reason">Reason</Label>
            <NativeSelect
              id="rejection-reason"
              className="w-full"
              value={reason}
              onChange={(event) => setReason(event.target.value as RejectionReason | '')}
              aria-invalid={problem !== '' && reason === ''}
            >
              <NativeSelectOption value="">Choose a reason</NativeSelectOption>
              {REJECTION_REASONS.map((option) => (
                <NativeSelectOption key={option.value} value={option.value}>
                  {option.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-2">
            <Label htmlFor="rejection-comment">
              {reason === 'other' ? 'Comment (required)' : 'Comment (optional)'}
            </Label>
            <Textarea
              id="rejection-comment"
              value={comment}
              maxLength={MAX_COMMENT_LENGTH}
              onChange={(event) => setComment(event.target.value)}
            />
          </div>
          {problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          {/* A plain button, not AlertDialogAction: that would close the dialog even when the
              form is not valid. */}
          <Button variant="destructive" disabled={busy} onClick={submit}>
            Reject application
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

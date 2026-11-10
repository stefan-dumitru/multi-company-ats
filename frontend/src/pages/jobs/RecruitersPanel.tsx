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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import type { Recruiter } from './types'

interface RecruitersPanelProps {
  /** Who is on the job now. */
  recruiters: Recruiter[]
  /** Every active recruiter of the company, to pick from; null while it is still loading. */
  companyRecruiters: Recruiter[] | null
  /** Why that list could not be loaded, if it could not. */
  companyRecruitersError: string
  onRetryCompanyRecruiters: () => void
  currentUserId: string
  busy: boolean
  onAdd: (recruiter: Recruiter) => void
  onRemove: (recruiter: Recruiter) => void
}

export default function RecruitersPanel({
  recruiters,
  companyRecruiters,
  companyRecruitersError,
  onRetryCompanyRecruiters,
  currentUserId,
  busy,
  onAdd,
  onRemove,
}: RecruitersPanelProps) {
  const [chosenId, setChosenId] = useState('')
  const [confirmingSelf, setConfirmingSelf] = useState<Recruiter | null>(null)

  const onJob = new Set(recruiters.map((person) => person.id))
  const available = (companyRecruiters ?? []).filter((person) => !onJob.has(person.id))
  const chosen = available.find((person) => person.id === chosenId)

  return (
    <section aria-labelledby="recruiters-heading" className="space-y-4">
      <h2 id="recruiters-heading" className="text-lg font-semibold">
        Recruiters
      </h2>

      {recruiters.length === 0 ? (
        <p className="text-muted-foreground">Nobody is assigned to this job yet.</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {recruiters.map((person) => (
            <li key={person.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
              <div>
                <span className="font-medium">{person.full_name}</span>
                {person.id === currentUserId && (
                  <span className="ml-1 text-muted-foreground">(you)</span>
                )}
                <span className="block text-sm text-muted-foreground">{person.email}</span>
              </div>
              <div className="flex items-center gap-3">
                {!person.is_active && <Badge variant="destructive">Deactivated</Badge>}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  aria-label={`Remove ${person.full_name}`}
                  onClick={() =>
                    person.id === currentUserId ? setConfirmingSelf(person) : onRemove(person)
                  }
                >
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {companyRecruitersError && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {companyRecruitersError}
          </p>
          <Button variant="outline" size="sm" onClick={onRetryCompanyRecruiters}>
            Try again
          </Button>
        </div>
      )}
      {companyRecruiters !== null && companyRecruiters.length === 0 && (
        <p className="text-sm text-muted-foreground">
          There are no recruiters in this company yet. An admin can invite one on the Users page.
        </p>
      )}
      {companyRecruiters !== null &&
        companyRecruiters.length > 0 &&
        (available.length === 0 ? (
          <p className="text-sm text-muted-foreground">Every recruiter is already on this job.</p>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="add-recruiter">Add a recruiter</Label>
              <NativeSelect
                id="add-recruiter"
                value={chosenId}
                onChange={(event) => setChosenId(event.target.value)}
              >
                <NativeSelectOption value="">Choose a recruiter</NativeSelectOption>
                {available.map((person) => (
                  <NativeSelectOption key={person.id} value={person.id}>
                    {person.full_name}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </div>
            <Button
              disabled={busy || chosen === undefined}
              onClick={() => {
                if (chosen) onAdd(chosen)
                setChosenId('')
              }}
            >
              Add recruiter
            </Button>
          </div>
        ))}

      <AlertDialog
        open={confirmingSelf !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmingSelf(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove yourself from this job?</AlertDialogTitle>
            <AlertDialogDescription>
              You will no longer see this job. An admin or a colleague on it can add you again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (confirmingSelf) onRemove(confirmingSelf)
                setConfirmingSelf(null)
              }}
            >
              Remove me
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

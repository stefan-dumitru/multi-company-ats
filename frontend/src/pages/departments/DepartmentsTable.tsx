import { useState } from 'react'
import type { FormEvent } from 'react'
import { messageOf } from '@/api/client'
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
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Department } from './types'

interface DepartmentsTableProps {
  departments: Department[]
  /** The department whose request is running; its buttons are switched off meanwhile. */
  busyId: string | null
  /** Rejects with an error whose message the row shows, keeping the rename open. */
  onRename: (department: Department, name: string) => Promise<void>
  onSetArchived: (department: Department, archived: boolean) => void
  onDelete: (department: Department) => void
}

export default function DepartmentsTable({
  departments,
  busyId,
  onRename,
  onSetArchived,
  onDelete,
}: DepartmentsTableProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')
  const [renameError, setRenameError] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState<Department | null>(null)

  function startRename(department: Department) {
    setRenamingId(department.id)
    setDraftName(department.name)
    setRenameError('')
  }

  async function saveRename(event: FormEvent, department: Department) {
    event.preventDefault()
    setRenameError('')
    try {
      await onRename(department, draftName)
      setRenamingId(null)
    } catch (failure) {
      setRenameError(messageOf(failure))
    }
  }

  return (
    <>
      <Table aria-label="Departments">
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {departments.map((department) => {
            const busy = busyId === department.id
            const renaming = renamingId === department.id
            return (
              <TableRow key={department.id}>
                <TableCell className="font-medium">
                  {renaming ? (
                    <form
                      onSubmit={(event) => void saveRename(event, department)}
                      className="flex flex-wrap items-center gap-2"
                    >
                      <Input
                        aria-label={`New name for ${department.name}`}
                        value={draftName}
                        onChange={(event) => setDraftName(event.target.value)}
                        className="max-w-64"
                        required
                      />
                      <Button type="submit" size="sm" disabled={busy}>
                        Save
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setRenamingId(null)}
                      >
                        Cancel
                      </Button>
                      {renameError && (
                        <p role="alert" className="w-full text-sm text-destructive">
                          {renameError}
                        </p>
                      )}
                    </form>
                  ) : (
                    department.name
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={department.is_archived ? 'outline' : 'secondary'}>
                    {department.is_archived ? 'Archived' : 'Active'}
                  </Badge>
                </TableCell>
                <TableCell className="space-x-2 text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    aria-label={`Rename ${department.name}`}
                    onClick={() => startRename(department)}
                  >
                    Rename
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    aria-label={`${department.is_archived ? 'Unarchive' : 'Archive'} ${department.name}`}
                    onClick={() => onSetArchived(department, !department.is_archived)}
                  >
                    {department.is_archived ? 'Unarchive' : 'Archive'}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    aria-label={`Delete ${department.name}`}
                    onClick={() => setConfirmingDelete(department)}
                  >
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <AlertDialog
        open={confirmingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmingDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {confirmingDelete?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This cannot be undone. A department that jobs have used cannot be deleted; archive it
              instead.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (confirmingDelete) onDelete(confirmingDelete)
                setConfirmingDelete(null)
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

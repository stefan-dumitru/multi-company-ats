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
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ROLE_LABELS, STAFF_ROLES } from '@/auth/roles'
import type { Role } from '@/auth/types'
import type { Member } from './types'

interface MembersTableProps {
  members: Member[]
  currentUserId: string
  /** The member whose request is running; their controls are switched off meanwhile. */
  busyId: string | null
  onChangeRole: (member: Member, role: Role) => void
  onDeactivate: (member: Member) => void
  onReactivate: (member: Member) => void
}

export default function MembersTable({
  members,
  currentUserId,
  busyId,
  onChangeRole,
  onDeactivate,
  onReactivate,
}: MembersTableProps) {
  const [confirming, setConfirming] = useState<Member | null>(null)

  return (
    <>
      <Table aria-label="Company members">
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((member) => {
            // Changing your own role or deactivating yourself from this screen is too easy to do
            // by accident: it would end your own admin access. Ask another admin instead. (The
            // server would allow it while another admin remains; this is only a safety net.)
            const isMe = member.id === currentUserId
            const busy = busyId === member.id
            return (
              <TableRow key={member.id}>
                <TableCell className="font-medium">
                  {member.full_name}
                  {isMe && <span className="ml-1 text-muted-foreground">(you)</span>}
                </TableCell>
                <TableCell>{member.email}</TableCell>
                <TableCell>
                  <NativeSelect
                    aria-label={`Role of ${member.full_name}`}
                    value={member.role}
                    disabled={isMe || busy}
                    onChange={(event) => onChangeRole(member, event.target.value as Role)}
                  >
                    {STAFF_ROLES.map((role) => (
                      <NativeSelectOption key={role} value={role}>
                        {ROLE_LABELS[role]}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </TableCell>
                <TableCell>
                  <Badge variant={member.is_active ? 'secondary' : 'destructive'}>
                    {member.is_active ? 'Active' : 'Deactivated'}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  {!isMe &&
                    (member.is_active ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        aria-label={`Deactivate ${member.full_name}`}
                        onClick={() => setConfirming(member)}
                      >
                        Deactivate
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        aria-label={`Reactivate ${member.full_name}`}
                        onClick={() => onReactivate(member)}
                      >
                        Reactivate
                      </Button>
                    ))}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <AlertDialog
        open={confirming !== null}
        onOpenChange={(open) => {
          if (!open) setConfirming(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Deactivate {confirming?.full_name}?</AlertDialogTitle>
            <AlertDialogDescription>
              They will be logged out straight away and cannot log in until you reactivate them.
              Everything they created is kept.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (confirming) onDeactivate(confirming)
                setConfirming(null)
              }}
            >
              Deactivate
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

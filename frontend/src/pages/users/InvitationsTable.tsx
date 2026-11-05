import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ROLE_LABELS } from '@/auth/roles'
import type { InvitationRow, InvitationStatus } from './types'

const STATUS_LABELS: Record<InvitationStatus, string> = {
  pending: 'Pending',
  accepted: 'Accepted',
  expired: 'Expired',
  revoked: 'Revoked',
}

const STATUS_VARIANTS: Record<InvitationStatus, 'secondary' | 'outline' | 'destructive'> = {
  pending: 'secondary',
  accepted: 'outline',
  expired: 'destructive',
  revoked: 'outline',
}

interface InvitationsTableProps {
  invitations: InvitationRow[]
  onResend: (invitation: InvitationRow) => void
}

export default function InvitationsTable({ invitations, onResend }: InvitationsTableProps) {
  if (invitations.length === 0) {
    return <p className="text-sm text-muted-foreground">No invitations yet.</p>
  }

  return (
    <Table aria-label="Invitations">
      <TableHeader>
        <TableRow>
          <TableHead>Email</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Expires</TableHead>
          <TableHead>
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invitations.map((invitation) => (
          <TableRow key={invitation.id}>
            <TableCell className="font-medium">{invitation.email}</TableCell>
            <TableCell>{ROLE_LABELS[invitation.role]}</TableCell>
            <TableCell>
              <Badge variant={STATUS_VARIANTS[invitation.status]}>
                {STATUS_LABELS[invitation.status]}
              </Badge>
            </TableCell>
            <TableCell>
              {/* Stored in UTC; shown in the viewer's own time zone. */}
              {new Date(invitation.expires_at).toLocaleDateString(undefined, {
                dateStyle: 'medium',
              })}
            </TableCell>
            <TableCell className="text-right">
              {/* Sending again replaces the old link, so it only makes sense while that link is
                  still the live one (pending) or has run out (expired). */}
              {(invitation.status === 'pending' || invitation.status === 'expired') && (
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Send a new link to ${invitation.email}`}
                  onClick={() => onResend(invitation)}
                >
                  Send a new link
                </Button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

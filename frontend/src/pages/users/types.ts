import type { Role } from '@/auth/types'

/** A company member as the API describes them to an admin. */
export interface Member {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  deactivated_at: string | null
  last_login_at: string | null
  created_at: string
}

export type InvitationStatus = 'pending' | 'accepted' | 'expired' | 'revoked'

/** An invitation as listed. The link itself is never part of this: it is shown once, at creation. */
export interface InvitationRow {
  id: string
  email: string
  role: Role
  status: InvitationStatus
  created_at: string
  expires_at: string
}

export interface CreatedInvitation {
  invitation: InvitationRow
  token: string
  accept_path: string
}

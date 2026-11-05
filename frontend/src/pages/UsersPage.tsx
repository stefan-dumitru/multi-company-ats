import { useState } from 'react'
import { api, messageOf } from '@/api/client'
import { useResource } from '@/api/useResource'
import { useAuth } from '@/auth/AuthContext'
import type { Role } from '@/auth/types'
import { Button } from '@/components/ui/button'
import InvitationLink from './users/InvitationLink'
import InvitationsTable from './users/InvitationsTable'
import InviteForm from './users/InviteForm'
import MembersTable from './users/MembersTable'
import type { CreatedInvitation, InvitationRow, Member } from './users/types'

interface NewLink {
  email: string
  link: string
}

export default function UsersPage() {
  const { state } = useAuth()
  const members = useResource<Member[]>('/api/users')
  const invitations = useResource<InvitationRow[]>('/api/invitations')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const [newLink, setNewLink] = useState<NewLink | null>(null)

  const currentUserId = state.status === 'authenticated' ? state.user.id : ''

  /** Runs a change to one member, then reloads the list so the screen shows what the server has. */
  async function change(member: Member, request: () => Promise<unknown>) {
    setActionError('')
    setBusyId(member.id)
    try {
      await request()
    } catch (failure) {
      setActionError(messageOf(failure))
    } finally {
      setBusyId(null)
      // Also after a refused change: the list then shows the old value again instead of the
      // choice the admin just made.
      members.reload()
    }
  }

  async function createInvitation(email: string, role: Role) {
    const created = await api<CreatedInvitation>('/api/invitations', {
      method: 'POST',
      body: { email, role },
    })
    // Built here, in the browser, because the page and the API share one address.
    setNewLink({ email, link: `${window.location.origin}${created.accept_path}` })
    invitations.reload()
  }

  async function resend(invitation: InvitationRow) {
    setActionError('')
    try {
      await createInvitation(invitation.email, invitation.role)
    } catch (failure) {
      setActionError(messageOf(failure))
    }
  }

  return (
    <div className="space-y-10">
      <h1 className="text-2xl font-semibold">Users</h1>

      {actionError && (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      )}

      <section className="space-y-3" aria-labelledby="members-heading">
        <h2 id="members-heading" className="text-lg font-semibold">
          Members
        </h2>
        {members.loading && <p role="status">Loading…</p>}
        {members.error && (
          <div className="space-y-2">
            <p role="alert" className="text-sm text-destructive">
              {members.error}
            </p>
            <Button variant="outline" size="sm" onClick={members.reload}>
              Try again
            </Button>
          </div>
        )}
        {members.data && (
          <MembersTable
            members={members.data}
            currentUserId={currentUserId}
            busyId={busyId}
            onChangeRole={(member, role) =>
              void change(member, () =>
                api(`/api/users/${member.id}/role`, { method: 'PATCH', body: { role } }),
              )
            }
            onDeactivate={(member) =>
              void change(member, () =>
                api(`/api/users/${member.id}/deactivate`, { method: 'POST' }),
              )
            }
            onReactivate={(member) =>
              void change(member, () =>
                api(`/api/users/${member.id}/reactivate`, { method: 'POST' }),
              )
            }
          />
        )}
      </section>

      <section className="space-y-4" aria-labelledby="invite-heading">
        <h2 id="invite-heading" className="text-lg font-semibold">
          Invite someone
        </h2>
        <InviteForm onInvite={createInvitation} />
        {newLink && (
          <InvitationLink
            email={newLink.email}
            link={newLink.link}
            onDone={() => setNewLink(null)}
          />
        )}
      </section>

      <section className="space-y-3" aria-labelledby="invitations-heading">
        <h2 id="invitations-heading" className="text-lg font-semibold">
          Invitations
        </h2>
        {invitations.loading && <p role="status">Loading…</p>}
        {invitations.error && (
          <div className="space-y-2">
            <p role="alert" className="text-sm text-destructive">
              {invitations.error}
            </p>
            <Button variant="outline" size="sm" onClick={invitations.reload}>
              Try again
            </Button>
          </div>
        )}
        {invitations.data && <InvitationsTable invitations={invitations.data} onResend={resend} />}
      </section>
    </div>
  )
}

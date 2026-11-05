import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { messageOf } from '@/api/client'
import { INVITE_ROLES, ROLE_LABELS } from '@/auth/roles'
import type { Role } from '@/auth/types'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'

interface InviteFormProps {
  /** Creates the invitation. Rejects with an error whose message the form shows. */
  onInvite: (email: string, role: Role) => Promise<void>
}

export default function InviteForm({ onInvite }: InviteFormProps) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('recruiter')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const busy = useRef(false) // stops a second click before React has re-rendered the button

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy.current) return
    busy.current = true
    setError('')
    setSubmitting(true)
    try {
      await onInvite(email, role)
      setEmail('')
    } catch (failure) {
      setError(messageOf(failure))
    } finally {
      busy.current = false
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="min-w-64 flex-1">
        <FormField
          id="invite-email"
          label="Invite by email"
          type="email"
          value={email}
          onChange={setEmail}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="invite-role">Role</Label>
        <NativeSelect
          id="invite-role"
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
        >
          {INVITE_ROLES.map((option) => (
            <NativeSelectOption key={option} value={option}>
              {ROLE_LABELS[option]}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      <Button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Create invitation'}
      </Button>
      {error && (
        <p role="alert" className="w-full text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  )
}

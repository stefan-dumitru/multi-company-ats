import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { messageOf } from '@/api/client'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

export interface ProfileValues {
  full_name: string
  phone: string
  location: string
}

interface ProfileFormProps {
  initial: ProfileValues
  /** The email address: shown, never edited here. */
  email: string
  /** Saves the values. Rejects with an error whose message the form shows; the values stay. */
  onSave: (values: ProfileValues) => Promise<void>
}

// The same limits as the server (which is the one that enforces them).
const MAX_NAME = 200
const MAX_PHONE = 30
const MAX_LOCATION = 200

export default function ProfileForm({ initial, email, onSave }: ProfileFormProps) {
  const [values, setValues] = useState(initial)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const busy = useRef(false) // stops a second send before React has re-rendered the button

  function set(field: keyof ProfileValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setSaved(false)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy.current) return
    busy.current = true
    setError('')
    setSaved(false)
    setSaving(true)
    try {
      await onSave(values)
      setSaved(true)
    } catch (failure) {
      setError(messageOf(failure))
    } finally {
      busy.current = false
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-xl space-y-5">
      <FormField
        id="profile-name"
        label="Your name"
        autoComplete="name"
        value={values.full_name}
        onChange={(value) => set('full_name', value)}
        maxLength={MAX_NAME}
      />
      <div className="space-y-1">
        <p className="text-sm font-medium">Email</p>
        <p>{email}</p>
        <p className="text-sm text-muted-foreground">
          This is the address you log in with. It cannot be changed here.
        </p>
      </div>
      <FormField
        id="profile-phone"
        label="Phone (optional)"
        type="tel"
        autoComplete="tel"
        value={values.phone}
        onChange={(value) => set('phone', value)}
        maxLength={MAX_PHONE}
        required={false}
      />
      <FormField
        id="profile-location"
        label="Location (optional)"
        autoComplete="address-level2"
        value={values.location}
        onChange={(value) => set('location', value)}
        maxLength={MAX_LOCATION}
        required={false}
        hint="Where you are based, for example a city or country."
      />
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
        {saved && <p role="status">Profile saved.</p>}
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  )
}

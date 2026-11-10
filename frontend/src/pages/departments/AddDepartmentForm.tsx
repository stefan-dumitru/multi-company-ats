import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { messageOf } from '@/api/client'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'

interface AddDepartmentFormProps {
  /** Creates the department. Rejects with an error whose message the form shows. */
  onAdd: (name: string) => Promise<void>
}

export default function AddDepartmentForm({ onAdd }: AddDepartmentFormProps) {
  const [name, setName] = useState('')
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
      await onAdd(name)
      setName('')
    } catch (failure) {
      // The typed name stays, so a small fix is enough to try again.
      setError(messageOf(failure))
    } finally {
      busy.current = false
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="min-w-64 flex-1">
        <FormField id="department-name" label="Department name" value={name} onChange={setName} />
      </div>
      <Button type="submit" disabled={submitting}>
        {submitting ? 'Adding…' : 'Add department'}
      </Button>
      {error && (
        <p role="alert" className="w-full text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  )
}

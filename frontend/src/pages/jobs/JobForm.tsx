import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { messageOf } from '@/api/client'
import FormField from '@/components/FormField'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Textarea } from '@/components/ui/textarea'
import type { DepartmentChoice } from './types'

export interface JobFormValues {
  title: string
  location: string
  department_id: string
  description: string
}

interface JobFormProps {
  departments: DepartmentChoice[]
  initial?: JobFormValues
  submitLabel: string
  /** Sends the job. Rejects with an error whose message the form shows; the values stay. */
  onSubmit: (values: JobFormValues) => Promise<void>
}

const EMPTY: JobFormValues = { title: '', location: '', department_id: '', description: '' }

// The same limits as the server (which is the one that enforces them).
const MAX_SHORT_TEXT = 200
const MAX_DESCRIPTION = 20_000

export default function JobForm({
  departments,
  initial = EMPTY,
  submitLabel,
  onSubmit,
}: JobFormProps) {
  const [values, setValues] = useState<JobFormValues>(initial)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const busy = useRef(false) // stops a second click before React has re-rendered the button

  function set<Field extends keyof JobFormValues>(field: Field, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy.current) return
    busy.current = true
    setError('')
    setSubmitting(true)
    try {
      await onSubmit(values)
    } catch (failure) {
      setError(messageOf(failure))
    } finally {
      busy.current = false
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl space-y-5">
      <FormField
        id="job-title"
        label="Title"
        value={values.title}
        onChange={(value) => set('title', value)}
        maxLength={MAX_SHORT_TEXT}
      />
      <FormField
        id="job-location"
        label="Location"
        value={values.location}
        onChange={(value) => set('location', value)}
        maxLength={MAX_SHORT_TEXT}
        hint="A city, a country, or Remote."
      />
      <div className="space-y-2">
        <Label htmlFor="job-department">Department</Label>
        <NativeSelect
          id="job-department"
          value={values.department_id}
          onChange={(event) => set('department_id', event.target.value)}
          required
        >
          <NativeSelectOption value="">Choose a department</NativeSelectOption>
          {departments.map((department) => (
            <NativeSelectOption key={department.id} value={department.id}>
              {department.name}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-2">
        <Label htmlFor="job-description">Description</Label>
        <Textarea
          id="job-description"
          value={values.description}
          onChange={(event) => set('description', event.target.value)}
          maxLength={MAX_DESCRIPTION}
          required
        />
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={submitting}>
          {submitting ? 'Saving…' : submitLabel}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  )
}

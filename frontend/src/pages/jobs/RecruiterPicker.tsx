import { Link } from 'react-router'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import { Button } from '@/components/ui/button'
import type { Recruiter } from './types'

interface RecruiterPickerProps {
  /** The ids of the recruiters ticked so far. */
  selected: string[]
  onChange: (selected: string[]) => void
}

/**
 * Tick the recruiters a new job starts with. Loads its own list, so the rest of the form works even
 * if that list cannot be loaded. The server checks every id again: this is a convenience.
 */
export default function RecruiterPicker({ selected, onChange }: RecruiterPickerProps) {
  const recruiters = useResource<Page<Recruiter>>('/api/recruiters?page_size=100')
  // The server lists active recruiters only, and checks every chosen id again.
  const choices = recruiters.data?.items ?? []

  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((chosen) => chosen !== id) : [...selected, id])
  }

  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Recruiters</legend>
      <p className="text-sm text-muted-foreground">
        Optional. A job needs at least one recruiter before it can be published.
      </p>
      {recruiters.loading && !recruiters.data && <p role="status">Loading…</p>}
      {recruiters.error && !recruiters.data && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {recruiters.error}
          </p>
          <Button type="button" variant="outline" size="sm" onClick={recruiters.reload}>
            Try again
          </Button>
        </div>
      )}
      {recruiters.data && choices.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No recruiters in your company yet.{' '}
          <Link to="/users" className="text-primary underline underline-offset-4">
            Invite one on the Users page
          </Link>
          , then add them to the job.
        </p>
      )}
      <ul className="space-y-1">
        {choices.map((person) => (
          <li key={person.id} className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selected.includes(person.id)}
                onChange={() => toggle(person.id)}
              />
              {person.full_name}
            </label>
            <span className="text-sm break-all text-muted-foreground">{person.email}</span>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}

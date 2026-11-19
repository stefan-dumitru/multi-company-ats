import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { fromLocalInputValue, toLocalInputValue } from '@/lib/format'
import type { Interview, InterviewChanges, Interviewer } from './types'

const MIN_DURATION = 5
const MAX_DURATION = 480

interface InterviewFormProps {
  /** The interview being rescheduled, or nothing for a new one. */
  initial?: Interview
  /** A request is running; the form is switched off meanwhile. */
  busy: boolean
  /** Called with what to send: everything for a new interview, only what changed for an existing
   *  one (an empty object means nothing changed). */
  onSubmit: (changes: InterviewChanges) => void
  onDiscard: () => void
}

/** The form to schedule an interview, or to change one. The server checks everything again. */
export default function InterviewForm({ initial, busy, onSubmit, onDiscard }: InterviewFormProps) {
  const interviewers = useResource<Page<Interviewer>>('/api/interviewers?page_size=100')
  const [roundName, setRoundName] = useState(initial?.round_name ?? '')
  const [when, setWhen] = useState(initial ? toLocalInputValue(initial.scheduled_at) : '')
  const [duration, setDuration] = useState(String(initial?.duration_minutes ?? 60))
  const [location, setLocation] = useState(initial?.location ?? '')
  const [chosen, setChosen] = useState<string[]>(initial?.participants.map((p) => p.user_id) ?? [])
  const [problem, setProblem] = useState('')

  // The people to choose from: the company's active interviewers, and anyone already assigned who
  // is not among them (deactivated since), so that they can be taken off.
  const choices: { id: string; name: string; email?: string; deactivated: boolean }[] = []
  for (const person of interviewers.data?.items ?? []) {
    choices.push({ id: person.id, name: person.full_name, email: person.email, deactivated: false })
  }
  for (const person of initial?.participants ?? []) {
    if (!choices.some((choice) => choice.id === person.user_id)) {
      choices.push({ id: person.user_id, name: person.full_name, deactivated: true })
    }
  }

  function toggle(id: string) {
    setChosen((now) => (now.includes(id) ? now.filter((other) => other !== id) : [...now, id]))
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const minutes = Number(duration)
    // The server checks all of this too; here it only saves a round trip.
    if (roundName.trim() === '') return setProblem('Enter a round name.')
    if (when === '') return setProblem('Choose a date and time.')
    if (location.trim() === '') return setProblem('Enter a location.')
    if (!Number.isInteger(minutes) || minutes < MIN_DURATION || minutes > MAX_DURATION) {
      return setProblem(`The duration must be between ${MIN_DURATION} and ${MAX_DURATION} minutes.`)
    }
    if (chosen.length === 0) return setProblem('Choose at least one interviewer.')
    setProblem('')

    // In the order the list shows them, so the same people always give the same request.
    const wanted = choices.filter((choice) => chosen.includes(choice.id)).map((choice) => choice.id)
    const all: Required<InterviewChanges> = {
      round_name: roundName.trim(),
      scheduled_at: fromLocalInputValue(when),
      duration_minutes: minutes,
      location: location.trim(),
      interviewer_ids: wanted,
    }
    if (!initial) return onSubmit(all)

    const changes: InterviewChanges = {}
    if (all.round_name !== initial.round_name) changes.round_name = all.round_name
    if (new Date(all.scheduled_at).getTime() !== new Date(initial.scheduled_at).getTime()) {
      changes.scheduled_at = all.scheduled_at
    }
    if (all.duration_minutes !== initial.duration_minutes) {
      changes.duration_minutes = all.duration_minutes
    }
    if (all.location !== initial.location) changes.location = all.location
    const before = initial.participants.map((p) => p.user_id)
    const same =
      before.length === wanted.length && before.every((person) => wanted.includes(person))
    if (!same) changes.interviewer_ids = wanted
    onSubmit(changes)
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border p-4">
      <div className="space-y-2">
        <Label htmlFor="interview-round">Round name</Label>
        <Input
          id="interview-round"
          value={roundName}
          maxLength={100}
          onChange={(event) => setRoundName(event.target.value)}
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="interview-when">Date and time</Label>
          <Input
            id="interview-when"
            type="datetime-local"
            value={when}
            onChange={(event) => setWhen(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">In your own time zone.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="interview-duration">Duration (minutes)</Label>
          <Input
            id="interview-duration"
            inputMode="numeric"
            value={duration}
            onChange={(event) => setDuration(event.target.value)}
          />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="interview-location">Location</Label>
        <Input
          id="interview-location"
          value={location}
          maxLength={300}
          onChange={(event) => setLocation(event.target.value)}
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Interviewers</legend>
        {interviewers.loading && !interviewers.data && <p role="status">Loading…</p>}
        {interviewers.error && !interviewers.data && (
          <div className="space-y-2">
            <p className="text-sm text-destructive">{interviewers.error}</p>
            <Button type="button" variant="outline" size="sm" onClick={interviewers.reload}>
              Try again
            </Button>
          </div>
        )}
        {interviewers.data && choices.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No interviewers in your company yet. A company admin can invite them.
          </p>
        )}
        <ul className="space-y-1">
          {choices.map((choice) => (
            <li key={choice.id} className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={chosen.includes(choice.id)}
                  onChange={() => toggle(choice.id)}
                />
                {choice.name}
              </label>
              {choice.email && (
                <span className="text-sm break-all text-muted-foreground">{choice.email}</span>
              )}
              {choice.deactivated && (
                <span className="text-sm text-muted-foreground">(deactivated)</span>
              )}
            </li>
          ))}
        </ul>
      </fieldset>

      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <Button type="submit" disabled={busy}>
          {initial ? 'Save changes' : 'Schedule interview'}
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onDiscard}>
          Discard
        </Button>
      </div>
    </form>
  )
}

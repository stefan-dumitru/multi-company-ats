import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api, messageOf } from '@/api/client'
import { useResource } from '@/api/useResource'
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
import { Button } from '@/components/ui/button'
import { formatDateTime } from '@/lib/format'

/** What GET /api/calendar answers (backend schemas/calendar.py). */
interface CalendarStatus {
  configured: boolean
  connected: boolean
  connected_at: string | null
}

// The codes the way back from Google can end with (backend services/calendar.py). The page shows
// our own words for them, never text taken from the address.
const ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Google did not allow access, so nothing was connected.',
  bad_state: 'That connection attempt expired or was not started here. Please start again.',
  missing_code: 'Google did not send what we needed. Please start again.',
  google_unavailable: 'Google could not be reached. Please try again in a few minutes.',
  google_refused: 'Google did not accept the connection. Please start again.',
  google_error: 'Google reported a problem. Please try again.',
  not_configured: 'Google Calendar isn’t set up on this server.',
}
const UNKNOWN_ERROR = 'Google Calendar could not be connected. Please try again.'

type Note = { kind: 'connected' } | { kind: 'error'; message: string } | null

/** The note for what Google sent the browser back with, read once when the page opens. */
function noteFromAddress(params: URLSearchParams): Note {
  const error = params.get('error')
  if (error !== null) return { kind: 'error', message: ERROR_MESSAGES[error] ?? UNKNOWN_ERROR }
  if (params.get('connected') === '1') return { kind: 'connected' }
  return null
}

/** A recruiter's Google Calendar connection: so their interviews appear on their calendar. */
export default function CalendarPage() {
  const status = useResource<CalendarStatus>('/api/calendar')
  const [searchParams, setSearchParams] = useSearchParams()
  // Kept in state and then removed from the address, so a refresh does not repeat the note.
  const [note] = useState<Note>(() => noteFromAddress(searchParams))
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false)

  useEffect(() => {
    if (searchParams.has('connected') || searchParams.has('error')) {
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  async function connect() {
    setBusy(true)
    setProblem('')
    try {
      const { url } = await api<{ url: string }>('/api/calendar/connect', { method: 'POST' })
      // Leaves this app for Google's own window; the button stays off until the page is gone.
      window.location.assign(url)
    } catch (failure) {
      setProblem(messageOf(failure))
      setBusy(false)
    }
  }

  async function disconnect() {
    setBusy(true)
    setProblem('')
    try {
      await api('/api/calendar/connection', { method: 'DELETE' })
      status.reload()
    } catch (failure) {
      setProblem(messageOf(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">Google Calendar</h1>

      {note?.kind === 'connected' && (
        <p role="status" className="text-sm">
          Google Calendar is connected.
        </p>
      )}
      {note?.kind === 'error' && (
        <p role="alert" className="text-sm text-destructive">
          {note.message}
        </p>
      )}

      {status.loading && !status.data && <p role="status">Loading…</p>}
      {status.error && !status.data && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {status.error}
          </p>
          <Button variant="outline" size="sm" onClick={status.reload}>
            Try again
          </Button>
        </div>
      )}

      {status.data && !status.data.configured && (
        <p className="text-muted-foreground">
          Google Calendar isn’t set up on this server. Interviews are still scheduled and emailed.
        </p>
      )}

      {status.data && status.data.configured && !status.data.connected && (
        <section className="space-y-3">
          <p>Not connected.</p>
          <p className="text-muted-foreground">
            Connect your Google account and the interviews you schedule appear on your primary
            calendar, with the interviewers as guests. Google sends no invitations of its own: the
            emails from this app still go out. We only ask for permission to manage events.
          </p>
          <Button onClick={connect} disabled={busy}>
            {busy ? 'Connecting…' : 'Connect Google Calendar'}
          </Button>
        </section>
      )}

      {status.data && status.data.configured && status.data.connected && (
        <section className="space-y-3">
          <p>
            Connected since{' '}
            {status.data.connected_at ? formatDateTime(status.data.connected_at) : 'earlier'}.
          </p>
          <p className="text-muted-foreground">
            Interviews you schedule from now on appear on your primary calendar, and an older one
            appears when it next changes. Changes and cancellations follow. Disconnecting leaves the
            events already in Google as they are.
          </p>
          <Button variant="outline" onClick={() => setConfirmingDisconnect(true)} disabled={busy}>
            Disconnect
          </Button>
        </section>
      )}

      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}

      <AlertDialog open={confirmingDisconnect} onOpenChange={setConfirmingDisconnect}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect Google Calendar?</AlertDialogTitle>
            <AlertDialogDescription>
              Existing events stay in Google, but later changes to those interviews will not reach
              your calendar.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Stay connected</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                // The dialog closes itself when an action is pressed.
                void disconnect()
              }}
            >
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

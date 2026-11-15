import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, messageOf } from '@/api/client'
import type { Page } from '@/api/types'
import { useResource } from '@/api/useResource'
import Pager from '@/components/Pager'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { formatDate } from '@/lib/format'

const PAGE_SIZE = 20
// The same limit as the server, which is the one that enforces it.
const MAX_NOTE_LENGTH = 4000

interface Note {
  id: string
  author_name: string
  body: string
  created_at: string
}

interface NotesSectionProps {
  applicationId: string
  /** Recruiters may add notes; company admins only read them. The server decides either way. */
  canWrite: boolean
}

/**
 * The internal notes on an application: staff only, never edited or removed. Loads on its own, so
 * if it fails the rest of the page keeps working. Notes are typed by people: React shows them as
 * text, and the line breaks are kept.
 */
export default function NotesSection({ applicationId, canWrite }: NotesSectionProps) {
  const [page, setPage] = useState(1)
  const notes = useResource<Page<Note>>(
    `/api/applications/${applicationId}/notes?page=${page}&page_size=${PAGE_SIZE}`,
  )
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  async function add(event: FormEvent) {
    event.preventDefault()
    const body = text.trim()
    if (body === '') return
    setError('')
    setSending(true)
    try {
      await api(`/api/applications/${applicationId}/notes`, { method: 'POST', body: { body } })
      setText('')
      // The newest note is first, so go back to the first page to see it.
      if (page === 1) notes.reload()
      else setPage(1)
    } catch (failure) {
      setError(messageOf(failure)) // what was typed stays in the box
    } finally {
      setSending(false)
    }
  }

  return (
    <section aria-labelledby="notes-heading" className="space-y-3">
      <h2 id="notes-heading" className="text-lg font-semibold">
        Notes
      </h2>
      <p className="text-sm text-muted-foreground">
        Internal: only your company's staff see these, never the candidate.
      </p>

      {canWrite && (
        <form onSubmit={(event) => void add(event)} className="space-y-2">
          <Label htmlFor="new-note">Add a note</Label>
          <Textarea
            id="new-note"
            value={text}
            maxLength={MAX_NOTE_LENGTH}
            onChange={(event) => setText(event.target.value)}
          />
          <Button type="submit" disabled={sending || text.trim() === ''}>
            Add note
          </Button>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </form>
      )}

      {notes.loading && !notes.data && <p role="status">Loading…</p>}
      {notes.error && !notes.data && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {notes.error}
          </p>
          <Button variant="outline" size="sm" onClick={notes.reload}>
            Try again
          </Button>
        </div>
      )}
      {notes.data && notes.data.total === 0 && (
        <p className="text-muted-foreground">No notes yet.</p>
      )}
      {notes.data && notes.data.total > 0 && notes.data.items.length === 0 && (
        // Rows went away while this page was open, so this page no longer exists.
        <div className="space-y-2">
          <p className="text-muted-foreground">There are no notes on this page any more.</p>
          <Button variant="outline" size="sm" onClick={() => setPage(1)}>
            Back to the first page
          </Button>
        </div>
      )}
      {notes.data && notes.data.items.length > 0 && (
        <>
          <ul className="space-y-3">
            {notes.data.items.map((item) => (
              <li key={item.id} className="space-y-1 rounded-lg border p-3">
                <p className="text-sm text-muted-foreground">
                  {`${item.author_name}, ${formatDate(item.created_at)}`}
                </p>
                <p className="break-words whitespace-pre-wrap">{item.body}</p>
              </li>
            ))}
          </ul>
          <Pager
            page={notes.data.page}
            pageSize={notes.data.page_size}
            total={notes.data.total}
            onChange={setPage}
          />
        </>
      )}
    </section>
  )
}

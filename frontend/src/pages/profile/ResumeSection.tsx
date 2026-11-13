import { useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { api, ApiError, messageOf } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { formatBytes, formatDate } from '@/lib/format'

export interface ResumeInfo {
  filename: string
  size_bytes: number
  uploaded_at: string
}

interface ResumeSectionProps {
  /** The resume on file, or null when there is none yet. */
  resume: ResumeInfo | null
  /** Called after a successful upload, so the page can load the new details. */
  onUploaded: () => void
}

// The same limit as the server, which is the one that enforces it. Checking here only saves the
// candidate from waiting for a large upload that would be refused.
const MAX_BYTES = 5 * 1024 * 1024
const STORAGE_DOWN = 'Resume storage is not available right now. Please try again later.'

/** The server hides the text of its own failures, so storage being down is recognised by its code. */
function uploadMessage(failure: unknown): string {
  if (failure instanceof ApiError && failure.code === 'storage_unavailable') return STORAGE_DOWN
  return messageOf(failure)
}

export default function ResumeSection({ resume, onUploaded }: ResumeSectionProps) {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [uploaded, setUploaded] = useState(false)
  const [uploading, setUploading] = useState(false)
  const busy = useRef(false) // stops a second send before React has re-rendered the button
  const input = useRef<HTMLInputElement>(null)

  function handleChoose(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null
    setUploaded(false)
    setError('')
    if (chosen !== null && chosen.size > MAX_BYTES) {
      setError('This file is larger than 5 MB. Choose a smaller PDF or Word file.')
      setFile(null)
      return
    }
    setFile(chosen)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy.current || file === null) return
    busy.current = true
    setError('')
    setUploaded(false)
    setUploading(true)
    try {
      await api(`/api/profile/resume?filename=${encodeURIComponent(file.name)}`, {
        method: 'PUT',
        file,
      })
      setUploaded(true)
      setFile(null)
      if (input.current) input.current.value = ''
      onUploaded()
    } catch (failure) {
      // The chosen file stays, so the same one can simply be tried again.
      setError(uploadMessage(failure))
    } finally {
      busy.current = false
      setUploading(false)
    }
  }

  return (
    <section aria-labelledby="resume-heading" className="max-w-xl space-y-4">
      <h2 id="resume-heading" className="text-lg font-semibold">
        Resume
      </h2>

      {resume ? (
        <div className="space-y-1 rounded-md border p-4">
          <p>
            <span className="font-medium">{resume.filename}</span>
          </p>
          <p className="text-sm text-muted-foreground">
            {formatBytes(resume.size_bytes)} · Uploaded {formatDate(resume.uploaded_at)}
          </p>
          {/* A new tab, so that if the download fails the profile page is not replaced by an error. */}
          <a
            href="/api/profile/resume"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-primary underline underline-offset-4"
          >
            Download
          </a>
        </div>
      ) : (
        <p className="text-muted-foreground">No resume yet. You need one to apply for jobs.</p>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="space-y-2">
          <Label htmlFor="resume-file">Choose a PDF or Word file (up to 5 MB)</Label>
          <Input
            ref={input}
            id="resume-file"
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={handleChoose}
          />
        </div>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={file === null || uploading}>
            {uploading ? 'Uploading…' : resume ? 'Replace resume' : 'Upload resume'}
          </Button>
          {uploaded && <p role="status">Resume uploaded.</p>}
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </form>
    </section>
  )
}

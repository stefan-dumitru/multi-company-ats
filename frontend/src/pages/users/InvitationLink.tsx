import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface InvitationLinkProps {
  email: string
  link: string
  onDone: () => void
}

/**
 * Shows a new invitation's link. The server has already queued the invitation email; the link is
 * shown here as well, once, so the admin can pass it on themselves if the email goes astray.
 */
export default function InvitationLink({ email, link, onDone }: InvitationLinkProps) {
  const field = useRef<HTMLInputElement>(null)
  const [copyMessage, setCopyMessage] = useState('')

  async function copy() {
    try {
      await navigator.clipboard.writeText(link)
      setCopyMessage('Copied.')
    } catch {
      // No clipboard access (an insecure page, or the browser said no): select the text so the
      // admin can copy it by hand.
      field.current?.select()
      setCopyMessage('Press Ctrl+C (or Cmd+C) to copy.')
    }
  }

  return (
    <section aria-label="New invitation" className="space-y-3 rounded-lg border bg-muted/40 p-4">
      <p>
        Invitation created for <strong>{email}</strong>. We have emailed the invitation to them. If
        it does not arrive, copy this link and send it yourself. It is shown only once: after you
        close this, it cannot be shown again.
      </p>
      <div className="space-y-2">
        <Label htmlFor="invitation-link">Invitation link</Label>
        <Input id="invitation-link" ref={field} readOnly value={link} />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" onClick={() => void copy()}>
          Copy link
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Done
        </Button>
        {copyMessage && (
          <span role="status" className="text-sm text-muted-foreground">
            {copyMessage}
          </span>
        )}
      </div>
    </section>
  )
}

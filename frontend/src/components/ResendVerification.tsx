import { useState } from 'react'
import { api, messageOf } from '@/api/client'
import { Button } from '@/components/ui/button'

/** Asks the server to email a fresh verification link to the logged-in user. */
export default function ResendVerification({ email }: { email: string }) {
  const [sending, setSending] = useState(false)
  const [sentTo, setSentTo] = useState('')
  const [error, setError] = useState('')

  async function resend() {
    if (sending) return
    setSending(true)
    setError('')
    setSentTo('')
    try {
      await api('/api/auth/resend-verification', { method: 'POST' })
      setSentTo(email)
    } catch (failure) {
      setError(messageOf(failure))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="space-y-2">
      <Button type="button" onClick={() => void resend()} disabled={sending}>
        {sending ? 'Sending…' : 'Send me a new link'}
      </Button>
      {sentTo && (
        <p role="status" className="text-sm text-muted-foreground">
          We sent a new link to {sentTo}. The older one no longer works.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

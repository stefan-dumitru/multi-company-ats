import { useResource } from '@/api/useResource'
import { Button } from '@/components/ui/button'

/**
 * "Continue with Google", shown only when this server has Google set up.
 *
 * It is a plain link, not a fetch: the browser itself goes to our server, which sends it on to
 * Google, so there is nothing for this page to handle and no token ever passes through it.
 * If the setting cannot be loaded the button is simply not offered: it is an extra way in, and a
 * password login must never be held up (or alarmed) by it.
 */
export default function GoogleSignIn() {
  const config = useResource<{ enabled: boolean }>('/api/auth/google/config')

  if (!config.data?.enabled) return null
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>
      <Button asChild variant="outline" className="w-full">
        <a href="/api/auth/google/start">Continue with Google</a>
      </Button>
    </div>
  )
}

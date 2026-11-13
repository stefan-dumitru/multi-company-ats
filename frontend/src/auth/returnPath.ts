/**
 * Where to send someone after they log in or register: the page they were trying to open, if it is
 * a page of this app, otherwise `fallback`.
 *
 * Anything that could lead to another site ("//evil.example", "https://...", "/\evil.example", which
 * browsers read as "//evil.example") is ignored, so the login and registration pages cannot be used
 * to bounce people to a look-alike site.
 */
export function safeReturnPath(routerState: unknown, fallback: string): string {
  const from = (routerState as { from?: unknown } | null | undefined)?.from
  if (
    typeof from === 'string' &&
    from.startsWith('/') &&
    !from.startsWith('//') &&
    !from.includes('\\')
  ) {
    return from
  }
  return fallback
}

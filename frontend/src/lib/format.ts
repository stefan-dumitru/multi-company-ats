/**
 * A date for display, in the viewer's own language and time zone. The server stores and sends
 * UTC; converting happens only here, at the edge (CLAUDE.md > Code Style).
 */
export function formatDate(isoTimestamp: string): string {
  return new Date(isoTimestamp).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

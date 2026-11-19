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

/** A file size for people: "512 B", "1.5 KB", "2.0 MB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * A date and time for display, in the viewer's own time zone, with the zone named so nobody has to
 * guess ("Dec 3, 2026, 2:30 PM GMT+1"). The server sends UTC.
 */
export function formatDateTime(isoTimestamp: string): string {
  return new Date(isoTimestamp).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  })
}

function two(value: number): string {
  return String(value).padStart(2, '0')
}

/** A moment as a `datetime-local` field wants it: the viewer's own wall-clock time. */
export function toLocalInputValue(isoTimestamp: string): string {
  const moment = new Date(isoTimestamp)
  return (
    `${moment.getFullYear()}-${two(moment.getMonth() + 1)}-${two(moment.getDate())}` +
    `T${two(moment.getHours())}:${two(moment.getMinutes())}`
  )
}

/** What the person typed in a `datetime-local` field (their own wall-clock time), as UTC. */
export function fromLocalInputValue(value: string): string {
  return new Date(value).toISOString()
}

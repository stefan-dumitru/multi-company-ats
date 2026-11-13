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

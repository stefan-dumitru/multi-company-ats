import { Button } from '@/components/ui/button'

interface PagerProps {
  /** The page being shown, counting from 1. */
  page: number
  pageSize: number
  /** How many rows there are in all, on every page. */
  total: number
  onChange: (page: number) => void
}

/** "Previous / Page 2 of 5 / Next". Shows nothing when everything fits on one page. */
export default function Pager({ page, pageSize, total, onChange }: PagerProps) {
  const pageCount = Math.ceil(total / pageSize)
  if (pageCount <= 1) return null

  return (
    <nav aria-label="Pages" className="flex items-center justify-end gap-3 text-sm">
      <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        Previous
      </Button>
      <span>
        Page {page} of {pageCount}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= pageCount}
        onClick={() => onChange(page + 1)}
      >
        Next
      </Button>
    </nav>
  )
}

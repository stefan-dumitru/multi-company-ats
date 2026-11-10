export type JobStatus = 'draft' | 'open' | 'closed'

export const STATUS_LABELS: Record<JobStatus, string> = {
  draft: 'Draft',
  open: 'Open',
  closed: 'Closed',
}

/** A job as listed (no description, no recruiters). */
export interface JobSummary {
  id: string
  title: string
  location: string
  status: JobStatus
  department_id: string
  department_name: string
  created_at: string
  opened_at: string | null
  closed_at: string | null
  version: number
  /** A draft or open job with no active recruiter: an admin should assign someone. */
  needs_reassignment: boolean
}

/** A department as the job forms and filters need it. */
export interface DepartmentChoice {
  id: string
  name: string
  is_archived: boolean
}

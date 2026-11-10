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

/** A recruiter, on a job or in the list to pick from. */
export interface Recruiter {
  id: string
  full_name: string
  email: string
  is_active: boolean
}

/** One job in full, as its page shows it. */
export interface JobDetail {
  id: string
  title: string
  location: string
  description: string
  status: JobStatus
  department: DepartmentChoice
  created_at: string
  opened_at: string | null
  closed_at: string | null
  /** Quoted back by every change, so a change made on an out-of-date page is refused. */
  version: number
  needs_reassignment: boolean
  recruiters: Recruiter[]
}

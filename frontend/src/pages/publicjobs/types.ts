/** A job as the public list shows it. Nothing here says who works on the job. */
export interface PublicJobSummary {
  id: string
  title: string
  location: string
  /** The first part of the description. */
  excerpt: string
  department_name: string
  company_id: string
  company_name: string
  opened_at: string | null
}

/** One open job in full. */
export interface PublicJob {
  id: string
  title: string
  location: string
  description: string
  department_name: string
  company_id: string
  company_name: string
  opened_at: string | null
}

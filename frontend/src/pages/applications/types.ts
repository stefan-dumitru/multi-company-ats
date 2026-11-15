export type ApplicationStage =
  'applied' | 'screening' | 'interview' | 'offer' | 'hired' | 'rejected' | 'withdrawn'

/** An application as its own candidate sees it (the API's MyApplicationOut). */
export interface MyApplication {
  id: string
  job_id: string
  job_title: string
  company_name: string
  stage: ApplicationStage
  applied_at: string
  /** Whether the job still takes applications: a withdrawn one can only come back if so. */
  job_is_open: boolean
}

export const STAGE_LABELS: Record<ApplicationStage, string> = {
  applied: 'Applied',
  screening: 'Screening',
  interview: 'Interview',
  offer: 'Offer',
  hired: 'Hired',
  rejected: 'Not selected',
  withdrawn: 'Withdrawn',
}

export const STAGE_BADGE: Record<ApplicationStage, 'default' | 'secondary' | 'outline'> = {
  applied: 'secondary',
  screening: 'secondary',
  interview: 'secondary',
  offer: 'default',
  hired: 'default',
  rejected: 'outline',
  withdrawn: 'outline',
}

/** Stages in which the candidate may still withdraw (the same set as the server's). */
export const WITHDRAWABLE: ApplicationStage[] = ['applied', 'screening', 'interview', 'offer']

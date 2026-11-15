import type { ApplicationStage } from '../applications/types'

export type RejectionReason =
  'skills_mismatch' | 'position_filled' | 'candidate_unresponsive' | 'failed_interview' | 'other'

/** The fixed list a recruiter chooses from (the same one the server accepts), in menu order. */
export const REJECTION_REASONS: { value: RejectionReason; label: string }[] = [
  { value: 'skills_mismatch', label: 'Skills or experience do not match' },
  { value: 'position_filled', label: 'Position filled / better candidate selected' },
  { value: 'candidate_unresponsive', label: 'Candidate withdrew interest or did not respond' },
  { value: 'failed_interview', label: 'Failed interview or assessment' },
  { value: 'other', label: 'Other (explain in the comment)' },
]

export const MAX_COMMENT_LENGTH = 2000

/** The stages in the order an application moves through them. */
export const PIPELINE: ApplicationStage[] = ['applied', 'screening', 'interview', 'offer', 'hired']

export interface HistoryEntry {
  from_stage: ApplicationStage | null
  to_stage: ApplicationStage
  changed_by_name: string
  changed_at: string
}

/** One application as staff see it (the API's ApplicationDetailOut). Never shown to candidates. */
export interface ApplicationDetail {
  id: string
  job_id: string
  job_title: string
  candidate_name: string
  candidate_email: string
  candidate_phone: string | null
  candidate_location: string | null
  stage: ApplicationStage
  /** What "move forward" would do now; null when there is nowhere to go. */
  next_stage: ApplicationStage | null
  /** Sent back with every change, so a stale change is refused. */
  version: number
  applied_at: string
  rejection: {
    from_stage: ApplicationStage
    reason: RejectionReason
    comment: string | null
  } | null
  history: HistoryEntry[]
}

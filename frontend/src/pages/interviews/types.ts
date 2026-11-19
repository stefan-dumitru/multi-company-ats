export type InterviewStatus = 'scheduled' | 'completed' | 'cancelled'
export type CalendarSyncStatus = 'not_requested' | 'pending' | 'synced' | 'failed'
export type Recommendation = 'strong_no' | 'no' | 'yes' | 'strong_yes'

export const INTERVIEW_STATUS_LABELS: Record<InterviewStatus, string> = {
  scheduled: 'Scheduled',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  strong_no: 'Strong no',
  no: 'No',
  yes: 'Yes',
  strong_yes: 'Strong yes',
}

export interface Participant {
  user_id: string
  full_name: string
  /** False once the person was deactivated: the interview then needs a new interviewer. */
  is_active: boolean
}

/** An interview as staff see it (the API's InterviewOut). */
export interface Interview {
  id: string
  application_id: string
  round_name: string
  scheduled_at: string
  duration_minutes: number
  location: string
  status: InterviewStatus
  /** Sent back with every change, so a stale change is refused. */
  version: number
  calendar_sync_status: CalendarSyncStatus
  needs_reassignment: boolean
  participants: Participant[]
  created_at: string
}

/** Who a recruiter can pick as an interviewer (the API's InterviewerOut). */
export interface Interviewer {
  id: string
  full_name: string
  email: string
}

/** One interviewer's evaluation, as staff read it (the API's ScorecardOut). */
export interface Scorecard {
  id: string
  interviewer_name: string
  overall_rating: number
  technical_rating: number
  communication_rating: number
  problem_solving_rating: number
  culture_fit_rating: number
  feedback: string
  recommendation: Recommendation
  submitted_at: string
}

/** The fields the schedule form can send. Reschedule sends only the ones that changed. */
export interface InterviewChanges {
  round_name?: string
  scheduled_at?: string
  duration_minutes?: number
  location?: string
  interviewer_ids?: string[]
}

/** One of an interviewer's own interviews, as listed (the API's MyInterviewOut). */
export interface MyInterviewRow {
  id: string
  round_name: string
  scheduled_at: string
  duration_minutes: number
  location: string
  status: InterviewStatus
  job_title: string
  /** Null once the interview is cancelled: the person may have been rejected or withdrawn. */
  candidate_name: string | null
  my_scorecard_submitted: boolean
}

export interface CandidateInfo {
  name: string
  email: string
  phone: string | null
  location: string | null
}

/** One interview for the interviewer assigned to it (the API's MyInterviewDetailOut). */
export interface MyInterviewDetail {
  id: string
  round_name: string
  scheduled_at: string
  duration_minutes: number
  location: string
  status: InterviewStatus
  job_title: string
  candidate: CandidateInfo | null
  my_scorecard: Scorecard | null
  /** Blind scoring: false until the interviewer has submitted, and `others` is empty until then. */
  others_visible: boolean
  others: Scorecard[]
}

/** What the scorecard form sends. */
export interface ScorecardSubmission {
  overall_rating: number
  technical_rating: number
  communication_rating: number
  problem_solving_rating: number
  culture_fit_rating: number
  feedback: string
  recommendation: Recommendation
}

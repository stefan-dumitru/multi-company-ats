export type Role = 'company_admin' | 'recruiter' | 'interviewer' | 'candidate'

/** What the API tells us about the logged-in user (never includes a password or its hash). */
export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  company_id: string | null
  /** When the user proved they own the address; null until they do. */
  email_verified_at: string | null
}

/** The server's answer to logging in, signing up or accepting an invitation. */
export interface SessionInfo {
  user: User
  csrf_token: string
}

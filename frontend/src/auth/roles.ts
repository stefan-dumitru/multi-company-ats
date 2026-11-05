import type { Role } from './types'

export const ROLE_LABELS: Record<Role, string> = {
  company_admin: 'Company admin',
  recruiter: 'Recruiter',
  interviewer: 'Interviewer',
  candidate: 'Candidate',
}

/** The roles a company member can have, in the order the member list offers them. */
export const STAFF_ROLES: Role[] = ['company_admin', 'recruiter', 'interviewer']

/** The same roles in the order the invite form offers them: the common case comes first. */
export const INVITE_ROLES: Role[] = ['recruiter', 'interviewer', 'company_admin']

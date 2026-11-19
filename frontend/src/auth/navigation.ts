import type { Role } from './types'

export interface NavItem {
  label: string
  to: string
}

/**
 * The menu links a role sees (ui-guidelines.md > Information Architecture). Hiding a link is only
 * convenience: every page and every API call is also checked by the server.
 */
export function navItemsFor(role: Role): NavItem[] {
  switch (role) {
    case 'company_admin':
      return [
        { label: 'Jobs', to: '/manage/jobs' },
        { label: 'Users', to: '/users' },
        { label: 'Departments', to: '/departments' },
      ]
    case 'recruiter':
      return [{ label: 'My jobs', to: '/manage/jobs' }]
    case 'candidate':
      return [
        { label: 'Jobs', to: '/jobs' },
        { label: 'My applications', to: '/applications' },
        { label: 'Profile', to: '/profile' },
      ]
    case 'interviewer':
      return [{ label: 'My interviews', to: '/interviews' }]
  }
}

/**
 * Where someone who has just signed up lands. A new company's admin has one job to do first:
 * invite their team. One rule here, so two redirects can never disagree.
 */
export function landingPathFor(role: Role): string {
  if (role === 'company_admin') return '/users'
  // A new candidate has one job to do first: confirm their email, which their profile page asks for.
  if (role === 'candidate') return '/profile'
  return '/'
}

/**
 * Where someone who logs in with no page to return to starts. An interviewer has one job here, so
 * they go straight to it; everyone else starts at the home page.
 */
export function afterLoginPathFor(role: Role): string {
  return role === 'interviewer' ? '/interviews' : '/'
}

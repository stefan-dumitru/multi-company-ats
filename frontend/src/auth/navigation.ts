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
      return [{ label: 'Users', to: '/users' }]
    case 'recruiter':
    case 'interviewer':
    case 'candidate':
      // Their pages arrive with the phases that build jobs, interviews and applications.
      return []
  }
}

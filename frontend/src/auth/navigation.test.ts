import { describe, expect, it } from 'vitest'
import { navItemsFor } from './navigation'

describe('navItemsFor', () => {
  it('gives company admins the Users page', () => {
    expect(navItemsFor('company_admin')).toEqual([{ label: 'Users', to: '/users' }])
  })

  it.each(['recruiter', 'interviewer', 'candidate'] as const)(
    'shows nothing the %s cannot use yet',
    (role) => {
      // Hiding links is cosmetic: the server decides who may do what.
      expect(navItemsFor(role)).toEqual([])
    },
  )
})

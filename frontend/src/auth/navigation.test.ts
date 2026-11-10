import { describe, expect, it } from 'vitest'
import { landingPathFor, navItemsFor } from './navigation'

describe('navItemsFor', () => {
  it('gives company admins the Jobs, Users and Departments pages', () => {
    expect(navItemsFor('company_admin')).toEqual([
      { label: 'Jobs', to: '/manage/jobs' },
      { label: 'Users', to: '/users' },
      { label: 'Departments', to: '/departments' },
    ])
  })

  it('gives recruiters their jobs', () => {
    expect(navItemsFor('recruiter')).toEqual([{ label: 'My jobs', to: '/manage/jobs' }])
  })

  it.each(['interviewer', 'candidate'] as const)('shows nothing the %s cannot use yet', (role) => {
    // Hiding links is cosmetic: the server decides who may do what.
    expect(navItemsFor(role)).toEqual([])
  })
})

describe('landingPathFor', () => {
  it('sends a company admin straight to the page where the team is managed', () => {
    expect(landingPathFor('company_admin')).toBe('/users')
  })

  it.each(['recruiter', 'interviewer', 'candidate'] as const)(
    'sends a %s to the home page until they have a page of their own',
    (role) => {
      expect(landingPathFor(role)).toBe('/')
    },
  )
})

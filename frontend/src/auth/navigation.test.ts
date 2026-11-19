import { describe, expect, it } from 'vitest'
import { afterLoginPathFor, landingPathFor, navItemsFor } from './navigation'

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

  it('gives candidates the job search, their applications and their profile', () => {
    expect(navItemsFor('candidate')).toEqual([
      { label: 'Jobs', to: '/jobs' },
      { label: 'My applications', to: '/applications' },
      { label: 'Profile', to: '/profile' },
    ])
  })

  it('gives interviewers their interviews and nothing else', () => {
    // Hiding links is cosmetic: the server decides who may do what.
    expect(navItemsFor('interviewer')).toEqual([{ label: 'My interviews', to: '/interviews' }])
  })
})

describe('landingPathFor', () => {
  it('sends a company admin straight to the page where the team is managed', () => {
    expect(landingPathFor('company_admin')).toBe('/users')
  })

  it('sends a new candidate to their profile, which asks them to confirm their email', () => {
    expect(landingPathFor('candidate')).toBe('/profile')
  })

  it('sends a recruiter to the home page until they have a page of their own', () => {
    expect(landingPathFor('recruiter')).toBe('/')
  })
})

describe('afterLoginPathFor', () => {
  it('sends an interviewer to their interviews, since that is all they have', () => {
    expect(afterLoginPathFor('interviewer')).toBe('/interviews')
  })

  it.each(['company_admin', 'recruiter', 'candidate'] as const)(
    'sends a %s to the home page',
    (role) => {
      expect(afterLoginPathFor(role)).toBe('/')
    },
  )
})

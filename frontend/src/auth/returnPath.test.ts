import { describe, expect, it } from 'vitest'
import { safeReturnPath } from './returnPath'

describe('safeReturnPath', () => {
  it('returns the page the user was trying to open', () => {
    expect(safeReturnPath({ from: '/jobs/abc' }, '/')).toBe('/jobs/abc')
  })

  it('keeps the search part of the address', () => {
    expect(safeReturnPath({ from: '/jobs?q=python&page=2' }, '/')).toBe('/jobs?q=python&page=2')
  })

  it.each([
    ['another site', 'https://evil.example/login'],
    ['a protocol-relative address', '//evil.example'],
    ['a backslash trick', '/\\evil.example'],
    ['a relative path', 'jobs'],
    ['an empty string', ''],
    ['a javascript address', 'javascript:alert(1)'],
  ])('ignores %s and uses the fallback', (_label, from) => {
    expect(safeReturnPath({ from }, '/profile')).toBe('/profile')
  })

  it.each([
    ['nothing', undefined],
    ['null', null],
    ['an empty object', {}],
    ['a number', { from: 42 }],
    ['an object', { from: { to: '/jobs' } }],
  ])('uses the fallback when the state is %s', (_label, state) => {
    expect(safeReturnPath(state, '/profile')).toBe('/profile')
  })
})

import { describe, expect, it } from 'vitest'
import { formatBytes, formatDateTime, fromLocalInputValue, toLocalInputValue } from './format'

describe('formatBytes', () => {
  it.each([
    [0, '0 B'],
    [1, '1 B'],
    [999, '999 B'],
    [1024, '1.0 KB'],
    [1536, '1.5 KB'],
    [102_400, '100.0 KB'],
    [1024 * 1024, '1.0 MB'],
    [5 * 1024 * 1024, '5.0 MB'],
    [2_621_440, '2.5 MB'],
  ])('shows %i bytes as %s', (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected)
  })
})

describe('date and time helpers', () => {
  it('shows a moment in the viewer’s zone and names the zone', () => {
    const shown = formatDateTime('2026-12-03T14:30:00Z')

    expect(shown).toContain('2026')
    expect(shown).toMatch(/[A-Z]{3,}|GMT|UTC/) // a zone name or offset is part of it
  })

  it('turns a typed local time into UTC and back without losing the minute', () => {
    const typed = '2030-03-05T14:30'

    const utc = fromLocalInputValue(typed)

    expect(utc).toBe(new Date(typed).toISOString())
    expect(utc.endsWith('Z')).toBe(true)
    expect(toLocalInputValue(utc)).toBe(typed)
  })

  it('writes a field value with zero padding', () => {
    expect(toLocalInputValue(new Date(2031, 0, 2, 3, 4).toISOString())).toBe('2031-01-02T03:04')
  })
})

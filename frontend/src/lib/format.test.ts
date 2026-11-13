import { describe, expect, it } from 'vitest'
import { formatBytes } from './format'

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

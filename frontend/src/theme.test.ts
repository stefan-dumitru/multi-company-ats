import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { followSystemTheme } from './theme'

/** A stand-in for the browser's "does the OS prefer dark?" question, which can change live. */
function stubSystemTheme(prefersDark: boolean) {
  const listeners = new Set<() => void>()
  const query = {
    matches: prefersDark,
    addEventListener: vi.fn((_event: string, listener: () => void) => listeners.add(listener)),
    removeEventListener: vi.fn((_event: string, listener: () => void) =>
      listeners.delete(listener),
    ),
  }
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(query))
  return {
    query,
    listeners,
    switchTo(dark: boolean) {
      query.matches = dark
      listeners.forEach((listener) => listener())
    },
  }
}

describe('followSystemTheme', () => {
  beforeEach(() => {
    document.documentElement.classList.remove('dark')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses the dark theme when the system prefers dark', () => {
    stubSystemTheme(true)

    followSystemTheme()

    expect(document.documentElement).toHaveClass('dark')
  })

  it('uses the light theme when the system prefers light', () => {
    stubSystemTheme(false)

    followSystemTheme()

    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('follows the system when it switches while the page is open', () => {
    const system = stubSystemTheme(false)
    followSystemTheme()

    system.switchTo(true)
    expect(document.documentElement).toHaveClass('dark')

    system.switchTo(false)
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('stops listening when told to', () => {
    const system = stubSystemTheme(false)
    const stop = followSystemTheme()

    stop()

    expect(system.listeners.size).toBe(0)
  })

  it('asks the browser the right question', () => {
    stubSystemTheme(false)

    followSystemTheme()

    expect(window.matchMedia).toHaveBeenCalledWith('(prefers-color-scheme: dark)')
  })
})

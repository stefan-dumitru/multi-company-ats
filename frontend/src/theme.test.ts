import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  currentTheme,
  followSystemTheme,
  getSavedTheme,
  saveTheme,
  setTheme,
  THEME_KEY,
} from './theme'

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
    localStorage.clear()
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

describe('a saved theme choice', () => {
  beforeEach(() => {
    document.documentElement.classList.remove('dark')
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('beats the system setting when the page loads', () => {
    stubSystemTheme(true)
    saveTheme('light')

    followSystemTheme()

    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('can be dark while the system is light', () => {
    stubSystemTheme(false)
    saveTheme('dark')

    followSystemTheme()

    expect(document.documentElement).toHaveClass('dark')
  })

  it('makes the page ignore later system changes', () => {
    const system = stubSystemTheme(false)
    saveTheme('light')
    followSystemTheme()

    system.switchTo(true)

    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('is remembered by setTheme, which also changes the page', () => {
    setTheme('dark')

    expect(document.documentElement).toHaveClass('dark')
    expect(getSavedTheme()).toBe('dark')
    expect(currentTheme()).toBe('dark')

    setTheme('light')

    expect(document.documentElement).not.toHaveClass('dark')
    expect(getSavedTheme()).toBe('light')
    expect(currentTheme()).toBe('light')
  })

  it('is stored under one key', () => {
    saveTheme('dark')

    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
  })

  it.each(['purple', '', 'null', 'DARK'])(
    'ignores a stored value that is not a theme (%j)',
    (junk) => {
      localStorage.setItem(THEME_KEY, junk)

      expect(getSavedTheme()).toBeNull()
    },
  )

  it('starts out with nothing saved', () => {
    expect(getSavedTheme()).toBeNull()
  })

  it('still switches the page when the browser refuses to store anything', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    })

    expect(getSavedTheme()).toBeNull()
    expect(() => setTheme('dark')).not.toThrow()
    expect(document.documentElement).toHaveClass('dark')
  })
})

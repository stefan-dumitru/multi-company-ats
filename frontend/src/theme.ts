const DARK_QUERY = '(prefers-color-scheme: dark)'

/** Where this browser remembers the person's own choice. */
export const THEME_KEY = 'ats-theme'

export type Theme = 'light' | 'dark'

/**
 * The theme the person picked with the switch, or null if they never did. Storage can be blocked
 * (private windows, strict settings), and then "not remembered" is the right answer, not a crash.
 */
export function getSavedTheme(): Theme | null {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    return saved === 'light' || saved === 'dark' ? saved : null
  } catch {
    return null
  }
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Blocked storage: the page still switches, it just will not be remembered next visit.
  }
}

function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

/** The theme the page shows right now. */
export function currentTheme(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

/** The person chose a theme: show it now and remember it. */
export function setTheme(theme: Theme): void {
  applyTheme(theme)
  saveTheme(theme)
}

/**
 * Pick the starting theme: the person's saved choice if they made one, otherwise the operating
 * system's (ui-guidelines.md: the preference defaults to the OS setting). While there is no saved
 * choice it also follows the OS if that changes while the page is open. The colours themselves are
 * CSS variables in index.css, switched by the `dark` class on <html>.
 *
 * Returns a function that stops following.
 */
export function followSystemTheme(): () => void {
  const query = window.matchMedia(DARK_QUERY)

  function apply() {
    // Read on every change, so a choice made after the page loaded stops the following too.
    const saved = getSavedTheme()
    if (saved !== null) {
      applyTheme(saved)
    } else {
      applyTheme(query.matches ? 'dark' : 'light')
    }
  }

  apply()
  query.addEventListener('change', apply)
  return () => query.removeEventListener('change', apply)
}

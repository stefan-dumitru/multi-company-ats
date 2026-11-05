const DARK_QUERY = '(prefers-color-scheme: dark)'

/**
 * Use the dark theme when the operating system does, and follow it if it changes while the page
 * is open (ui-guidelines.md: the preference defaults to the OS setting). The colours themselves are
 * CSS variables in index.css, switched by the `dark` class on <html>.
 *
 * Returns a function that stops following.
 */
export function followSystemTheme(): () => void {
  const query = window.matchMedia(DARK_QUERY)

  function apply() {
    document.documentElement.classList.toggle('dark', query.matches)
  }

  apply()
  query.addEventListener('change', apply)
  return () => query.removeEventListener('change', apply)
}

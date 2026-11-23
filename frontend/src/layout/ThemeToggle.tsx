import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { currentTheme, setTheme, type Theme } from '@/theme'

/** One button that flips between the light and the dark theme, and remembers the choice. */
export default function ThemeToggle() {
  // The page's class is the source of truth (main.tsx sets it before the first render); the state
  // only makes this button redraw when it changes.
  const [theme, setThemeState] = useState<Theme>(currentTheme)
  const next: Theme = theme === 'dark' ? 'light' : 'dark'

  function handleClick() {
    setTheme(next)
    setThemeState(next)
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={`Switch to ${next} theme`}
      onClick={handleClick}
      className="text-header-foreground hover:bg-header-foreground/15 hover:text-header-foreground"
    >
      {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  )
}

import { useEffect, useState } from 'react'
import { usePrefersReducedMotion } from '../motion'

type Theme = 'light' | 'dark'
const STORAGE_KEY = 'steamview-theme' // also read by the script in index.html
const systemDark = window.matchMedia('(prefers-color-scheme: dark)')

function savedTheme(): Theme | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'light' || saved === 'dark' ? saved : null
  } catch {
    return null // storage blocked, e.g. some private windows: just follow the system
  }
}

/** Switches between light and dark. The choice is remembered on this device; until someone picks,
    the page follows the system setting, including when it changes. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'))
  const reduced = usePrefersReducedMotion()

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const follow = () => { if (!savedTheme()) setTheme(systemDark.matches ? 'dark' : 'light') }
    systemDark.addEventListener('change', follow)
    return () => systemDark.removeEventListener('change', follow)
  }, [])

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // not remembered, but still switched
    }
    const apply = () => {
      document.documentElement.dataset.theme = next // straight away, so the cross-fade sees the new colors
      setTheme(next)
    }
    // Cross-fade between the two themes instead of snapping, where the browser can
    if (reduced || !document.startViewTransition) apply()
    else document.startViewTransition(apply)
  }

  const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
  return (
    <button type="button" className="theme-toggle" onClick={toggle} aria-label={label} title={label}>
      {theme === 'dark' ? (
        // Sun: what you'll get
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        // Moon
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
        </svg>
      )}
    </button>
  )
}

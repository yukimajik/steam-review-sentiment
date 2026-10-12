import { useEffect, useState } from 'react'

// The dashboard's sections, in page order. Each id is on a wrapper in App.
const SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'trend', label: 'Trend' },
  { id: 'playtime', label: 'Playtime' },
  { id: 'updates', label: 'Updates' },
  { id: 'topics', label: 'Topics' },
  { id: 'reviews', label: 'Reviews' },
] as const

type SectionId = (typeof SECTIONS)[number]['id']

/** Links to each section of the dashboard. The one being read is highlighted as you scroll. */
export function SectionNav() {
  const active = useActiveSection()
  return (
    <nav className="section-nav" aria-label="Dashboard sections">
      <ul>
        {SECTIONS.map((section) => (
          <li key={section.id}>
            <a href={`#${section.id}`} aria-current={active === section.id ? 'location' : undefined}>
              {section.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** The last section whose top has scrolled past a line just below the top bar; the last one at the very bottom. */
function useActiveSection(): SectionId {
  const [active, setActive] = useState<SectionId>('overview')
  useEffect(() => {
    let frame = 0
    function update() {
      frame = 0
      const line = (document.querySelector('.masthead')?.getBoundingClientRect().bottom ?? 0) + 96
      let current: SectionId = SECTIONS[0].id
      for (const { id } of SECTIONS) {
        const top = document.getElementById(id)?.getBoundingClientRect().top
        if (top !== undefined && top <= line) current = id
      }
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
      setActive(atBottom ? SECTIONS[SECTIONS.length - 1].id : current)
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update) } // at most once per frame
    schedule()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      cancelAnimationFrame(frame)
    }
  }, [])
  return active
}

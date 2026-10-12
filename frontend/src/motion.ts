// Small helpers for the page's few animations. Every animation checks usePrefersReducedMotion
// first: people whose system asks for less motion get the final state straight away.
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'

export const COUNT_MS = 800 // same length as the donut drawing, so the numbers land with it

const reducedQuery = typeof window === 'undefined' ? null : window.matchMedia('(prefers-reduced-motion: reduce)')

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      reducedQuery?.addEventListener('change', onChange)
      return () => reducedQuery?.removeEventListener('change', onChange)
    },
    () => reducedQuery?.matches ?? false,
  )
}

/** A ref for an element, and whether it has been at least a fifth on screen yet (stays true after). */
export function useSeenOnce<T extends Element>() {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    const element = ref.current
    if (seen || !element) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setSeen(true)
    }, { threshold: 0.2 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [seen])
  return [ref, seen] as const
}

/** Counts from 0 up to `target` over COUNT_MS, slowing down at the end. */
export function useCountUp(target: number): number {
  const reduced = usePrefersReducedMotion()
  const [value, setValue] = useState(0)
  useEffect(() => {
    if (reduced) return
    const start = performance.now()
    let frame = requestAnimationFrame(function tick(now) {
      const t = Math.min(1, (now - start) / COUNT_MS)
      setValue(target * (1 - (1 - t) ** 3)) // ease out
      if (t < 1) frame = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(frame)
  }, [target, reduced])
  return reduced ? target : value
}

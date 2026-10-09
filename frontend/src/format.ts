import type { Sentiment, Topic } from './api'

const integer = new Intl.NumberFormat('en-US')

export const formatCount = (n: number) => integer.format(n)

export const formatPct = (pct: number) => `${pct.toFixed(1)}%`

/** Model scores with an explicit sign, e.g. +0.44 / -0.53 / 0.00 */
export const formatScore = (score: number) => (score > 0 ? '+' : '') + score.toFixed(2)

/** "2026-08" -> "Aug 2026" */
export function formatMonth(month: string): string {
  const [year, m] = month.split('-').map(Number)
  return new Date(Date.UTC(year, m - 1, 1)).toLocaleDateString('en-US', {
    month: 'short', year: 'numeric', timeZone: 'UTC',
  })
}

/** ISO timestamp -> "Sep 22, 2026" */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Steam's formatting tags, e.g. [b]...[/b], [spoiler], [url=...]. The same list the
// backend strips before scoring (backend/app/sentiment.py); here they're removed for display.
const BBCODE_TAG = /\[\/?(?:h[1-3]|b|u|i|strike|spoiler|noparse|hr|url|quote|code|list|olist|table|tr|th|td|\*)(?:=[^\]]*)?\]/gi

export const stripFormatting = (text: string) => text.replace(BBCODE_TAG, '').trim()

export function formatPlaytime(minutes: number | null): string | null {
  if (minutes == null) return null
  return `${(minutes / 60).toFixed(1)} h played`
}

export const SENTIMENT_LABELS: Record<Sentiment, string> = {
  positive: 'Positive',
  neutral: 'Neutral',
  negative: 'Negative',
}

/** Chart colors, defined once in index.css. Blue/red are opposite poles, gray is the neutral midpoint. */
export const SENTIMENT_COLORS: Record<Sentiment, string> = {
  positive: 'var(--sentiment-positive)',
  neutral: 'var(--sentiment-neutral)',
  negative: 'var(--sentiment-negative)',
}

export const TOPIC_LABELS: Record<Topic, string> = {
  performance: 'Performance',
  bugs: 'Bugs',
  price: 'Price / value',
  story: 'Story',
  gameplay: 'Gameplay',
  graphics: 'Graphics',
  multiplayer: 'Multiplayer / servers',
  content: 'Content / length',
}

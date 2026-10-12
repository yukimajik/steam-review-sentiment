import { useState } from 'react'
import type { Sentiment, Summary } from '../api'
import { formatCount, formatPct, SENTIMENT_COLORS, SENTIMENT_LABELS } from '../format'

// The donut is drawn by hand rather than with Recharts so that positive (clockwise) and
// negative (counterclockwise) can both start at 12 o'clock: the seam at the top is where
// they meet, and the side that's bigger shows which way the game leans.
const CENTER = 100
const RADIUS = 82
const RING = 24 // thickness of the ring
const GAP = 2.4 // degrees of panel-colored gap between slices
const SEAM_TOP = -24 // the seam line starts above the ring

/** A point on the ring, `angle` degrees clockwise from 12 o'clock. */
function point(angle: number): string {
  const radians = (angle * Math.PI) / 180
  return `${(CENTER + RADIUS * Math.sin(radians)).toFixed(2)} ${(CENTER - RADIUS * Math.cos(radians)).toFixed(2)}`
}

/** An arc from one angle to another: clockwise if `to` is larger, otherwise counterclockwise. */
function arc(from: number, to: number): string {
  const sweep = to > from ? 1 : 0
  const large = Math.abs(to - from) > 180 ? 1 : 0
  return `M ${point(from)} A ${RADIUS} ${RADIUS} 0 ${large} ${sweep} ${point(to)}`
}

/** A slice covering `span` degrees from `start`, in `direction`, with half a gap taken off each end. */
function slicePath(start: number, span: number, direction: 1 | -1, gap: number): string {
  if (span >= 359.9) return `${arc(start, start + direction * 180)} ${arc(start + direction * 180, start + direction * 359.99)}`
  const length = Math.max(span - 2 * gap, 0.6) // a tiny share still shows as a sliver
  const from = start + direction * ((span - length) / 2)
  return arc(from, from + direction * length)
}

interface Slice {
  sentiment: Sentiment
  pct: number
  path: string
}

function toSlices(summary: Summary): Slice[] {
  const positive = summary.positive_pct * 3.6
  const negative = summary.negative_pct * 3.6
  const neutral = summary.neutral_pct > 0 ? Math.max(0, 360 - positive - negative) : 0 // closes the ring exactly
  const gap = [positive, neutral, negative].filter((span) => span > 0).length > 1 ? GAP / 2 : 0
  const slices: Slice[] = [
    { sentiment: 'positive', pct: summary.positive_pct, path: slicePath(0, positive, 1, gap) },
    { sentiment: 'neutral', pct: summary.neutral_pct, path: slicePath(positive, neutral, 1, gap) },
    { sentiment: 'negative', pct: summary.negative_pct, path: slicePath(360, negative, -1, gap) },
  ]
  return slices.filter((slice) => slice.pct > 0)
}

export function SentimentSplit({ summary }: { summary: Summary }) {
  const [active, setActive] = useState<Sentiment | null>(null) // hovered slice or number
  const slices = toSlices(summary)
  const description = (['positive', 'neutral', 'negative'] as const)
    .map((s) => `${SENTIMENT_LABELS[s]} ${formatPct(summary[`${s}_pct`])}`)
    .join(', ')
  const hover = (sentiment: Sentiment) => ({
    onMouseEnter: () => setActive(sentiment),
    onMouseLeave: () => setActive(null),
  })

  return (
    <div className="hero-body">
      <div className="hero-split">
        <h3>Sentiment breakdown</h3>
        <p className="note">Share of reviews the model labels negative, neutral or positive.</p>

        <div className={active ? 'split has-active' : 'split'}>
          <SplitSide sentiment="negative" pct={summary.negative_pct} active={active} {...hover('negative')} />
          <figure className="donut" role="img" aria-label={`Donut chart: ${description}`}>
            <svg viewBox={`0 ${SEAM_TOP} 200 ${200 - SEAM_TOP}`} aria-hidden="true">
              {slices.map((slice) => (
                <path
                  key={slice.sentiment}
                  d={slice.path}
                  pathLength={100} // lets CSS grow each slice from its start
                  className={`donut-arc is-${slice.sentiment}${active === slice.sentiment ? ' is-active' : ''}`}
                  stroke={SENTIMENT_COLORS[slice.sentiment]}
                  strokeWidth={RING}
                  fill="none"
                  {...hover(slice.sentiment)}
                />
              ))}
              <line className="donut-seam" x1={CENTER} x2={CENTER} y1={SEAM_TOP} y2={CENTER - RADIUS + RING / 2} />
            </svg>
            {/* The middle shows the total, or the hovered slice */}
            <div className="donut-center" aria-hidden="true">
              {active ? (
                <>
                  <strong>{formatPct(summary[`${active}_pct`])}</strong>
                  <span>{SENTIMENT_LABELS[active]}</span>
                </>
              ) : (
                <>
                  <strong>{formatCount(summary.total_reviews)}</strong>
                  <span>English reviews</span>
                </>
              )}
            </div>
          </figure>
          <SplitSide sentiment="positive" pct={summary.positive_pct} active={active} {...hover('positive')} />
          <p className={active === 'neutral' ? 'split-neutral is-active' : 'split-neutral'} {...hover('neutral')}>
            <span className="dot" style={{ background: SENTIMENT_COLORS.neutral }} />
            Neutral <strong>{formatPct(summary.neutral_pct)}</strong>
          </p>
        </div>
      </div>

      <Agreement summary={summary} />
    </div>
  )
}

function SplitSide({ sentiment, pct, active, onMouseEnter, onMouseLeave }: {
  sentiment: 'positive' | 'negative'
  pct: number
  active: Sentiment | null
  onMouseEnter: () => void
  onMouseLeave: () => void
}) {
  const className = `split-side is-${sentiment}${active === sentiment ? ' is-active' : ''}`
  return (
    <div className={className} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <p className="split-value">{formatPct(pct)}</p>
      <p className="split-label">
        <span className="dot" style={{ background: SENTIMENT_COLORS[sentiment] }} />
        {SENTIMENT_LABELS[sentiment]}
      </p>
    </div>
  )
}

function Agreement({ summary }: { summary: Summary }) {
  const gap = summary.agreement_pct - summary.baseline_pct
  const comparison =
    Math.abs(gap) < 0.05
      ? 'Same as'
      : `${Math.abs(gap).toFixed(1)} pts ${gap > 0 ? 'above' : 'below'}`

  return (
    <div className="hero-agreement">
      <h3>Model agreement</h3>
      <p className="agreement-value">{formatPct(summary.agreement_pct)}</p>
      {/* Bar: the model's agreement. Tick: the baseline it should beat. */}
      <div className="meter" aria-hidden="true">
        <span className="meter-fill" style={{ width: `${summary.agreement_pct}%` }} />
        <span className="meter-baseline" style={{ left: `${summary.baseline_pct}%` }} />
      </div>
      <p className="note">
        How often the label matches the player’s own vote. {comparison} the {formatPct(summary.baseline_pct)} you’d get
        by always guessing the more common vote, marked by the tick.
      </p>
    </div>
  )
}

export function SentimentSplitSkeleton() {
  return (
    <div className="hero-body" aria-hidden="true">
      <div className="hero-split">
        <h3>Sentiment breakdown</h3>
        <div className="split">
          <div className="split-side is-negative"><div className="skeleton skeleton-value" /></div>
          <div className="donut"><div className="skeleton skeleton-donut" /></div>
          <div className="split-side is-positive"><div className="skeleton skeleton-value" /></div>
        </div>
      </div>
      <div className="hero-agreement">
        <h3>Model agreement</h3>
        <div className="skeleton skeleton-value" />
        <div className="skeleton skeleton-text" />
      </div>
    </div>
  )
}

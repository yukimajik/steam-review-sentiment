import type { Summary } from '../api'
import { formatCount, formatPct } from '../format'

export function SummaryCards({ summary }: { summary: Summary }) {
  const gap = summary.agreement_pct - summary.baseline_pct
  const comparison =
    Math.abs(gap) < 0.05
      ? 'Same as'
      : `${Math.abs(gap).toFixed(1)} pts ${gap > 0 ? 'above' : 'below'}`

  return (
    <div className="cards">
      <div className="card stat">
        <p className="stat-label">Total reviews</p>
        <p className="stat-value">{formatCount(summary.total_reviews)}</p>
        <p className="stat-note">English reviews analyzed</p>
      </div>
      <div className="card stat">
        <p className="stat-label">Positive</p>
        <p className="stat-value">{formatPct(summary.positive_pct)}</p>
        <p className="stat-note">of reviews, as scored by VADER</p>
      </div>
      <div className="card stat">
        <p className="stat-label">Model agreement</p>
        <p className="stat-value">{formatPct(summary.agreement_pct)}</p>
        <p className="stat-note">
          {comparison} the {formatPct(summary.baseline_pct)} baseline from always guessing the more common vote
        </p>
      </div>
    </div>
  )
}

export function SummaryCardsSkeleton() {
  return (
    <div className="cards" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="card stat">
          <div className="skeleton skeleton-text" style={{ width: '40%' }} />
          <div className="skeleton skeleton-value" />
          <div className="skeleton skeleton-text" style={{ width: '70%' }} />
        </div>
      ))}
    </div>
  )
}

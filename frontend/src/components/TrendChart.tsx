import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
  type TooltipContentProps,
} from 'recharts'
import type { TrendWeek } from '../api'
import { formatCount, formatDay, formatScore } from '../format'

const DAY_MS = 24 * 60 * 60 * 1000
const WEEK_MS = 7 * DAY_MS

interface Point {
  x: number // the middle of the week, in milliseconds
  week: string
  avg_compound: number | null // null for a week with no reviews, which breaks the line
  review_count: number
}

const weekStart = (week: string) => Date.parse(`${week}T00:00:00Z`)

/** One point per week from the first to the last, so weeks without reviews leave a gap in the line. */
function toPoints(weeks: TrendWeek[]): Point[] {
  const byWeek = new Map(weeks.map((w) => [w.week, w]))
  const points: Point[] = []
  for (let start = weekStart(weeks[0].week); start <= weekStart(weeks[weeks.length - 1].week); start += WEEK_MS) {
    const week = new Date(start).toISOString().slice(0, 10)
    const stored = byWeek.get(week)
    points.push({ x: start + WEEK_MS / 2, week, avg_compound: stored?.avg_compound ?? null, review_count: stored?.review_count ?? 0 })
  }
  return points
}

/** Ticks at the start of each month for a long range, otherwise at the start of each week.
    Recharts drops ticks that would overlap, so narrow screens show fewer. */
function ticksBetween(start: number, end: number): { ticks: number[]; format: (t: number) => string } {
  const date = (t: number, options: Intl.DateTimeFormatOptions) =>
    new Date(t).toLocaleDateString('en-US', { ...options, timeZone: 'UTC' })
  if (end - start > 10 * WEEK_MS) {
    const ticks: number[] = []
    const first = new Date(start)
    for (let m = 1; ; m++) {
      const t = Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + m, 1)
      if (t > end) break
      ticks.push(t)
    }
    return { ticks, format: (t) => date(t, { month: 'short', year: 'numeric' }) }
  }
  const ticks: number[] = []
  for (let t = start; t <= end; t += WEEK_MS) ticks.push(t)
  return { ticks, format: (t) => date(t, { month: 'short', day: 'numeric' }) }
}

// `updateTimes`: when each game update was posted, in milliseconds, drawn as dashed lines
export function TrendChart({ weeks, updateTimes }: { weeks: TrendWeek[]; updateTimes: number[] }) {
  const points = toPoints(weeks)
  const last = weeks[weeks.length - 1]
  const start = weekStart(weeks[0].week)
  const end = weekStart(last.week) + WEEK_MS
  const { ticks, format } = ticksBetween(start, end)
  const shownUpdates = updateTimes.filter((t) => t >= start && t <= end)

  // Label only the most recent point; the axis and tooltip carry the rest
  const renderEndLabel = ({ x, y, index }: { x?: number | string; y?: number | string; index?: number }) =>
    index === points.length - 1 && x != null && y != null ? (
      <text x={Number(x)} y={Number(y) - 12} textAnchor="middle" className="end-label">
        {formatScore(last.avg_compound)}
      </text>
    ) : null

  return (
    <section className="card chart-card">
      <h3>Average sentiment by week</h3>
      <p className="chart-note">
        Model score from −1 (likely Not recommended) to +1 (likely Recommended), by review date
        {shownUpdates.length > 0 && '. Dashed lines mark game updates'}
      </p>
      <div
        className="trend"
        role="img"
        aria-label={`Line chart of average sentiment by week${shownUpdates.length ? `, with ${shownUpdates.length} updates marked` : ''}. ` +
          `Most recent: week of ${formatDay(last.week)}, ${formatScore(last.avg_compound)}.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 24, right: 24, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey="x"
              type="number"
              scale="time"
              domain={[start, end]}
              ticks={ticks}
              tickFormatter={format}
              stroke="var(--axis)"
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickLine={false}
            />
            <YAxis
              domain={[-1, 1]}
              ticks={[-1, -0.5, 0, 0.5, 1]}
              stroke="var(--axis)"
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickLine={false}
              axisLine={false}
            />
            <ReferenceLine y={0} stroke="var(--axis)" />
            {shownUpdates.map((time) => (
              <ReferenceLine key={time} x={time} stroke="var(--text-muted)" strokeDasharray="4 3" />
            ))}
            <Tooltip content={TrendTooltip} cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }} />
            <Line
              type="linear"
              dataKey="avg_compound"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={{ r: 3, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
              activeDot={{ r: 5, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
              label={renderEndLabel}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="data-table">
        <summary>Show data table</summary>
        <table>
          <thead>
            <tr><th scope="col">Week of</th><th scope="col">Average score</th><th scope="col">Reviews</th></tr>
          </thead>
          <tbody>
            {weeks.map((w) => (
              <tr key={w.week}>
                <td>{formatDay(w.week)}</td>
                <td>{formatScore(w.avg_compound)}</td>
                <td>{formatCount(w.review_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}

function TrendTooltip({ active, payload }: TooltipContentProps) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload as Point
  return (
    <div className="tooltip">
      <span>Week of {formatDay(point.week)}</span>
      {point.avg_compound === null ? (
        <span>No reviews stored</span>
      ) : (
        <>
          <strong>{formatScore(point.avg_compound)}</strong>
          <span>{formatCount(point.review_count)} reviews</span>
        </>
      )}
    </div>
  )
}

export function ChartSkeleton({ title }: { title: string }) {
  return (
    <section className="card chart-card" aria-hidden="true">
      <h3>{title}</h3>
      <div className="skeleton skeleton-chart" />
    </section>
  )
}

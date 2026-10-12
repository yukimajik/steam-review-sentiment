import { useEffect, useState } from 'react'
import {
  CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
  type TooltipContentProps,
} from 'recharts'
import { ApiError, getOfftopic, isAbort, type Offtopic, type OfftopicPeriod, type TrendWeek } from '../api'
import { formatCount, formatDay, formatScore } from '../format'
import { GapFill } from './GapFill'

const DAY_MS = 24 * 60 * 60 * 1000
const WEEK_MS = 7 * DAY_MS
// A week's average needs this many reviews to join the line; fewer are hollow dots. A single review
// scored 0 made a cliff in Silksong's chart. Same minimum as the playtime groups and update comparison.
const MIN_WEEK_REVIEWS = 30

interface Point {
  x: number // the middle of the week, in milliseconds
  week: string
  avg_compound: number | null // null for a week with no reviews
  solid: number | null // the average, if the week has enough reviews; null breaks the line
  sparse: number | null // the average, if it has too few; drawn as a hollow dot
  review_count: number
}

const weekStart = (week: string) => Date.parse(`${week}T00:00:00Z`)

/** One point per week from the first to the last, so weeks without reviews are bridged by the dashed join. */
function toPoints(weeks: TrendWeek[]): Point[] {
  const byWeek = new Map(weeks.map((w) => [w.week, w]))
  const points: Point[] = []
  for (let start = weekStart(weeks[0].week); start <= weekStart(weeks[weeks.length - 1].week); start += WEEK_MS) {
    const week = new Date(start).toISOString().slice(0, 10)
    const avg = byWeek.get(week)?.avg_compound ?? null
    const count = byWeek.get(week)?.review_count ?? 0
    const enough = count >= MIN_WEEK_REVIEWS
    points.push({
      x: start + WEEK_MS / 2, week, avg_compound: avg, review_count: count,
      solid: enough ? avg : null, sparse: enough ? null : avg,
    })
  }
  return points
}

/** Ticks at the start of each month for a long range, otherwise at the start of each week.
    Month labels are short ("Nov"), with the year only on the first tick and on January, so they
    fit; Recharts still drops ticks that would overlap, so narrow screens show fewer. */
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
    const format = (t: number) =>
      t === ticks[0] || new Date(t).getUTCMonth() === 0
        ? date(t, { month: 'short', year: 'numeric' })
        : date(t, { month: 'short' })
    return { ticks, format }
  }
  const ticks: number[] = []
  for (let t = start; t <= end; t += WEEK_MS) ticks.push(t)
  return { ticks, format: (t) => date(t, { month: 'short', day: 'numeric' }) }
}

// `updateTimes`: when each game update was posted, in milliseconds, drawn as dashed lines.
// `weeksToFill`: past weeks under 30 reviews not yet asked about; `onFilled` reloads the dashboard once they are.
export function TrendChart({ appId, weeks, updateTimes, weeksToFill, onFilled }: {
  appId: number; weeks: TrendWeek[]; updateTimes: number[]; weeksToFill: number; onFilled: () => void
}) {
  const offtopic = useOfftopic(appId)
  const points = toPoints(weeks)
  const last = weeks[weeks.length - 1]
  const start = weekStart(weeks[0].week)
  // Flagged periods during or after the stored reviews are drawn, and the axis stretches to show
  // them: Steam leaves their reviews out, so otherwise the line would just stop with no explanation
  const drawn = (offtopic?.data?.periods ?? [])
    .map((p) => ({ from: Math.max(Date.parse(p.start), start), to: Date.parse(p.end) }))
    .filter((p) => p.to > start)
  const end = Math.max(weekStart(last.week) + WEEK_MS, ...drawn.map((p) => p.to))
  const { ticks, format } = ticksBetween(start, end)
  const shownUpdates = updateTimes.filter((t) => t >= start && t <= end)

  const hasGaps = points.some((p) => p.review_count === 0)
  const hasSparse = points.some((p) => p.sparse !== null)
  // Label only the most recent week on the line; the axis and tooltip carry the rest
  const lastSolid = points.findLastIndex((p) => p.solid !== null)
  const renderEndLabel = ({ x, y, index }: { x?: number | string; y?: number | string; index?: number }) =>
    index === lastSolid && x != null && y != null ? (
      <text x={Number(x)} y={Number(y) - 12} textAnchor="middle" className="end-label">
        {formatScore(points[lastSolid].solid!)}
      </text>
    ) : null

  return (
    <section className="section">
      <div className="section-head">
        <h3>Average sentiment by week</h3>
        <p className="note">
          Model score from −1 (likely Not recommended) to +1 (likely Recommended), by review date
          {shownUpdates.length > 0 && '. Dashed lines mark game updates'}
          {drawn.length > 0 && '. Hatched areas mark periods Steam flagged as off-topic review activity'}.
          {hasSparse && ` Hollow dots are weeks with fewer than ${MIN_WEEK_REVIEWS} reviews, too few to rely on.`}
          {(hasSparse || hasGaps) && ' A faint dashed line joins every week that has reviews, so the line doesn’t break where the solid line stops.'}
        </p>
      </div>
      <div className="section-body">
        <div
          className="trend"
          role="img"
          aria-label={`Line chart of average sentiment by week${shownUpdates.length ? `, with ${shownUpdates.length} updates marked` : ''}` +
            `${drawn.length ? `, and ${drawn.length} off-topic ${drawn.length === 1 ? 'period' : 'periods'} shaded` : ''}. ` +
            `Most recent: week of ${formatDay(last.week)}, ${formatScore(last.avg_compound)}.`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 24, right: 24, bottom: 0, left: -12 }}>
              <defs>
              <pattern id="offtopic-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-3)" strokeWidth="1.5" strokeOpacity="0.45" />
              </pattern>
            </defs>
            {/* Tint the two halves, so above zero reads as leaning Recommended and below as Not recommended */}
              <ReferenceArea y1={0} y2={1} fill="var(--sentiment-positive)" fillOpacity={0.06} stroke="none"
                label={{ value: 'Leans Recommended', position: 'insideTopLeft', fill: 'var(--ink-3)', fontSize: 12 }} />
              <ReferenceArea y1={-1} y2={0} fill="var(--sentiment-negative)" fillOpacity={0.06} stroke="none"
                label={{ value: 'Leans Not recommended', position: 'insideBottomLeft', fill: 'var(--ink-3)', fontSize: 12 }} />
              <CartesianGrid vertical={false} stroke="var(--grid)" />
            {drawn.map((p) => (
              <ReferenceArea key={p.from} x1={p.from} x2={p.to} fill="url(#offtopic-hatch)" stroke="none"
                label={{ value: 'Off-topic', position: 'insideTop', fill: 'var(--ink-3)', fontSize: 12 }} />
            ))}
              <XAxis
                dataKey="x"
                type="number"
                scale="time"
                domain={[start, end]}
                ticks={ticks}
                tickFormatter={format}
                stroke="var(--axis)"
                tick={{ fill: 'var(--ink-3)', fontSize: 12 }}
                tickLine={false}
              />
              <YAxis
                domain={[-1, 1]}
                ticks={[-1, -0.5, 0, 0.5, 1]}
                stroke="var(--axis)"
                tick={{ fill: 'var(--ink-3)', fontSize: 12 }}
                tickLine={false}
                axisLine={false}
              />
              <ReferenceLine y={0} stroke="var(--ink)" strokeOpacity={0.5} />
              {shownUpdates.map((time) => (
                <ReferenceLine key={time} x={time} stroke="var(--ink-3)" strokeDasharray="4 3" />
              ))}
              <Tooltip content={TrendTooltip} cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }} />
              {/* Every week with reviews, faint and dashed, under the solid line: where the solid line
                  stops (a hollow dot or a week with none) this keeps the line from breaking */}
              <Line
                type="linear"
                dataKey="avg_compound"
                stroke="var(--ink-3)"
                strokeWidth={1.5}
                strokeDasharray="3 4"
                strokeOpacity={0.7}
                connectNulls
                dot={false}
                activeDot={false}
                isAnimationActive={false}
              />
              <Line
                type="linear"
                dataKey="solid"
                stroke="var(--ink)"
                strokeWidth={2}
                dot={{ r: 3, fill: 'var(--ink)', stroke: 'var(--panel)', strokeWidth: 2 }}
                activeDot={{ r: 5, fill: 'var(--ink)', stroke: 'var(--panel)', strokeWidth: 2 }}
                label={renderEndLabel}
                isAnimationActive={false}
              />
              {/* Weeks with too few reviews: hollow dots, joined only by the dashed line */}
              <Line
                type="linear"
                dataKey="sparse"
                stroke="none"
                dot={{ r: 3.5, fill: 'var(--panel)', stroke: 'var(--ink-3)', strokeWidth: 1.5 }}
                activeDot={{ r: 5, fill: 'var(--panel)', stroke: 'var(--ink-3)', strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        {weeksToFill > 0 && <GapFill key={appId} appId={appId} weeks={weeksToFill} onFilled={onFilled} />}
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
        <OfftopicNote state={offtopic} />
      </div>
    </section>
  )
}

/** The game's flagged periods, loaded on their own so a Steam problem only affects this note. */
function useOfftopic(appId: number) {
  const [state, setState] = useState<{ appId: number; data?: Offtopic; error?: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController() // a newer game cancels this request
    getOfftopic(appId, controller.signal)
      .then((data) => setState({ appId, data }))
      .catch((error) => {
        if (isAbort(error)) return
        setState({ appId, error: error instanceof ApiError ? error.message : 'Something went wrong.' })
      })
    return () => controller.abort()
  }, [appId])
  return state?.appId === appId ? state : null // null while loading
}

function OfftopicNote({ state }: { state: { data?: Offtopic; error?: string } | null }) {
  if (state === null) return null
  if (state.error) return <p className="note">Couldn’t check Steam for off-topic review periods. {state.error}</p>
  const periods = state.data?.periods ?? []
  if (periods.length === 0) return <p className="note">Steam hasn’t flagged any off-topic review activity for this game.</p>
  return (
    <div>
      <p className="note">
        Steam flagged off-topic review activity (such as a review bomb) for this game. It leaves every review posted
        in a flagged period out of its review results, which is where these reviews come from, so they’re missing
        here too.
      </p>
      <ul className="offtopic-periods">
        {periods.map((p) => <li key={p.start}>{describePeriod(p)}</li>)}
      </ul>
    </div>
  )
}

function describePeriod(p: OfftopicPeriod): string {
  const dates = `${formatDay(p.start.slice(0, 10))} to ${formatDay(p.end.slice(0, 10))}`
  const when = p.still_flagged ? `${dates} (still flagged when checked)` : dates
  return `${when}: ${formatCount(p.reviews_left_out)} English ${p.reviews_left_out === 1 ? 'review' : 'reviews'} ` +
    `left out, ${formatCount(p.negative_left_out)} of them Not recommended.`
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
          <span>
            {formatCount(point.review_count)} {point.review_count === 1 ? 'review' : 'reviews'}
            {point.review_count < MIN_WEEK_REVIEWS && ', too few to rely on'}
          </span>
        </>
      )}
    </div>
  )
}

export function ChartSkeleton({ title }: { title: string }) {
  return (
    <section className="section" aria-hidden="true">
      <div className="section-head">
        <h3>{title}</h3>
        <div className="skeleton skeleton-text" />
      </div>
      <div className="section-body">
        <div className="skeleton skeleton-chart" />
      </div>
    </section>
  )
}

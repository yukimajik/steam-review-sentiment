import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
  type TooltipContentProps,
} from 'recharts'
import type { TrendMonth } from '../api'
import { formatCount, formatMonth, formatScore } from '../format'

export function TrendChart({ months }: { months: TrendMonth[] }) {
  const last = months[months.length - 1]

  // Label only the most recent point; the axis and tooltip carry the rest
  const renderEndLabel = ({ x, y, index }: { x?: number | string; y?: number | string; index?: number }) =>
    index === months.length - 1 && x != null && y != null ? (
      <text x={Number(x)} y={Number(y) - 12} textAnchor="middle" className="end-label">
        {formatScore(last.avg_compound)}
      </text>
    ) : null

  return (
    <section className="card chart-card">
      <h3>Average sentiment by month</h3>
      <p className="chart-note">Model score from −1 (likely Not recommended) to +1 (likely Recommended), by review date</p>
      <div
        className="trend"
        role="img"
        aria-label={`Line chart of average sentiment by month. Most recent: ${formatMonth(last.month)}, ${formatScore(last.avg_compound)}.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={months} margin={{ top: 24, right: 24, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey="month"
              tickFormatter={formatMonth}
              stroke="var(--axis)"
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickLine={false}
              padding={{ left: 24, right: 24 }}
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
            <Tooltip content={TrendTooltip} cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }} />
            <Line
              type="linear"
              dataKey="avg_compound"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={{ r: 4, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
              activeDot={{ r: 6, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
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
            <tr><th scope="col">Month</th><th scope="col">Average score</th><th scope="col">Reviews</th></tr>
          </thead>
          <tbody>
            {months.map((m) => (
              <tr key={m.month}>
                <td>{formatMonth(m.month)}</td>
                <td>{formatScore(m.avg_compound)}</td>
                <td>{formatCount(m.review_count)}</td>
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
  const month = payload[0].payload as TrendMonth
  return (
    <div className="tooltip">
      <span>{formatMonth(month.month)}</span>
      <strong>{formatScore(month.avg_compound)}</strong>
      <span>{formatCount(month.review_count)} reviews</span>
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

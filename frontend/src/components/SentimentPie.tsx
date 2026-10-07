import { Pie, PieChart, ResponsiveContainer, Tooltip, type TooltipContentProps } from 'recharts'
import type { Sentiment, Summary } from '../api'
import { formatPct, SENTIMENT_COLORS, SENTIMENT_LABELS } from '../format'

interface Slice {
  sentiment: Sentiment
  name: string
  value: number
  fill: string
}

export function SentimentPie({ summary }: { summary: Summary }) {
  const slices: Slice[] = (['positive', 'neutral', 'negative'] as const).map((sentiment) => ({
    sentiment,
    name: SENTIMENT_LABELS[sentiment],
    value: summary[`${sentiment}_pct`],
    fill: SENTIMENT_COLORS[sentiment],
  }))

  const description = slices.map((s) => `${s.name} ${formatPct(s.value)}`).join(', ')

  return (
    <section className="card chart-card">
      <h3>Sentiment breakdown</h3>
      <div className="pie-layout">
        <div className="pie" role="img" aria-label={`Pie chart: ${description}`}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={slices}
                dataKey="value"
                nameKey="name"
                startAngle={90}
                endAngle={-270} // clockwise from 12 o'clock
                outerRadius="95%"
                stroke="var(--surface)"
                strokeWidth={2} // surface-colored gap between slices
                isAnimationActive={false}
              />
              <Tooltip content={PieTooltip} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        {/* The legend doubles as the data table: every value is readable without hovering */}
        <ul className="legend">
          {slices.map((slice) => (
            <li key={slice.sentiment}>
              <span className="swatch" style={{ background: slice.fill }} />
              <span className="legend-name">{slice.name}</span>
              <span className="legend-value">{formatPct(slice.value)}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function PieTooltip({ active, payload }: TooltipContentProps) {
  if (!active || !payload?.length) return null
  const slice = payload[0].payload as Slice
  return (
    <div className="tooltip">
      <strong>{formatPct(slice.value)}</strong>
      <span>{slice.name}</span>
    </div>
  )
}

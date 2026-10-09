import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Rectangle, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
  type BarShapeProps, type TooltipContentProps,
} from 'recharts'
import type { Topic, TopicExample, Topics, TopicSummary } from '../api'
import { formatCount, formatPct, formatScore, SENTIMENT_COLORS, TOPIC_LABELS } from '../format'

interface Row {
  topic: Topic
  label: string
  mentionPct: number // share of all reviews that mention the topic
  complaintPct: number // negative, so the bar extends left of zero
  praisePct: number
  summary: TopicSummary
}

// Rendered with a key per game, so a new game starts on its own most-mentioned topic.
export function TopicBreakdown({ data }: { data: Topics }) {
  const [selected, setSelected] = useState<Topic | null>(null)
  const mentioned = data.topics.filter((t) => t.mentions > 0)
  const shown = data.topics.find((t) => t.topic === selected) ?? mentioned[0]

  if (!shown) {
    return (
      <section className="card topics">
        <h3>What players talk about</h3>
        <p className="empty">
          None of these reviews mention the topics tracked here: performance, bugs, price, story, gameplay, graphics,
          multiplayer and content.
        </p>
      </section>
    )
  }

  const share = (count: number) => (100 * count) / data.total_reviews
  const rows: Row[] = data.topics.map((summary) => ({
    topic: summary.topic,
    label: TOPIC_LABELS[summary.topic],
    mentionPct: share(summary.mentions),
    complaintPct: -share(summary.negative),
    praisePct: share(summary.positive),
    summary,
  }))
  // Same scale on both sides, so zero sits in the middle and praise and complaints compare fairly
  const largest = Math.max(...rows.map((r) => Math.max(r.praisePct, -r.complaintPct)))
  const limit = Math.max(10, Math.ceil(largest / 10) * 10)

  const mostPraised = maxBy(data.topics, (t) => t.positive)
  const mostCriticized = maxBy(data.topics, (t) => t.negative)
  const description =
    `Bar chart of praise and complaints by topic. Most praised: ${TOPIC_LABELS[mostPraised.topic]}, ` +
    `${formatCount(mostPraised.positive)} reviews. Most complained about: ${TOPIC_LABELS[mostCriticized.topic]}, ` +
    `${formatCount(mostCriticized.negative)} reviews.`

  // Bars for the selected topic are solid, the others faded
  const renderBar = (props: BarShapeProps) => (
    <Rectangle {...props} fillOpacity={(props.payload as Row).topic === shown.topic ? 1 : 0.45} />
  )
  const select = (bar: { payload?: Row }) => bar.payload && setSelected(bar.payload.topic)

  return (
    <section className="card topics">
      <h3>What players talk about</h3>
      <p className="chart-note">
        Share of all {formatCount(data.total_reviews)} reviews that praise or complain about each topic, most mentioned
        first. Click a bar or a topic below to see examples.
      </p>
      <ul className="topic-legend">
        <li><span className="swatch" style={{ background: SENTIMENT_COLORS.negative }} /> Complaints</li>
        <li><span className="swatch" style={{ background: SENTIMENT_COLORS.positive }} /> Praise</li>
      </ul>
      <div className="topics-chart" role="img" aria-label={description}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" stackOffset="sign" margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid horizontal={false} stroke="var(--grid)" />
            <XAxis
              type="number"
              domain={[-limit, limit]}
              ticks={[-limit, -limit / 2, 0, limit / 2, limit]}
              tickFormatter={(value: number) => `${Math.abs(value)}%`}
              stroke="var(--axis)"
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={140}
              stroke="var(--axis)"
              tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
              tickLine={false}
              axisLine={false}
            />
            <ReferenceLine x={0} stroke="var(--axis)" />
            <Tooltip content={TopicTooltip} cursor={{ fill: 'var(--grid)', fillOpacity: 0.5 }} />
            <Bar dataKey="complaintPct" stackId="topic" fill={SENTIMENT_COLORS.negative} shape={renderBar}
              onClick={select} cursor="pointer" isAnimationActive={false} />
            <Bar dataKey="praisePct" stackId="topic" fill={SENTIMENT_COLORS.positive} shape={renderBar}
              onClick={select} cursor="pointer" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <details className="data-table">
        <summary>Show data table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Topic</th><th scope="col">Mentions</th><th scope="col">Praise</th>
              <th scope="col">Neutral</th><th scope="col">Complaints</th>
            </tr>
          </thead>
          <tbody>
            {data.topics.map((t) => (
              <tr key={t.topic}>
                <td>{TOPIC_LABELS[t.topic]}</td>
                <td>{formatCount(t.mentions)}</td>
                <td>{formatCount(t.positive)}</td>
                <td>{formatCount(t.neutral)}</td>
                <td>{formatCount(t.negative)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <div className="filters" role="group" aria-label="Show examples for a topic">
        {data.topics.map((t) => (
          <button key={t.topic} type="button" className="filter" aria-pressed={t.topic === shown.topic}
            onClick={() => setSelected(t.topic)}>
            {TOPIC_LABELS[t.topic]}
          </button>
        ))}
      </div>

      {shown.mentions === 0 ? (
        <p className="empty">No reviews mention {TOPIC_LABELS[shown.topic].toLowerCase()}.</p>
      ) : (
        <div className="topic-examples">
          <ExampleColumn kind="praise" topic={shown.topic} count={shown.positive} examples={shown.praise} />
          <ExampleColumn kind="complaints" topic={shown.topic} count={shown.negative} examples={shown.complaints} />
        </div>
      )}
    </section>
  )
}

function ExampleColumn({ kind, topic, count, examples }: {
  kind: 'praise' | 'complaints'
  topic: Topic
  count: number
  examples: TopicExample[]
}) {
  const color = SENTIMENT_COLORS[kind === 'praise' ? 'positive' : 'negative']
  return (
    <div>
      <h4 className="topic-examples-title">
        <span className="dot" style={{ background: color }} />
        {kind === 'praise' ? 'Praise' : 'Complaints'}
        <span className="topic-examples-count">{formatCount(count)} reviews</span>
      </h4>
      {examples.length === 0 ? (
        <p className="empty">No {kind} about {TOPIC_LABELS[topic].toLowerCase()} in these reviews.</p>
      ) : (
        <ul className="excerpts">
          {examples.map((example) => (
            // Keyed by topic too, so an expanded excerpt collapses when another topic is picked
            <Excerpt key={`${topic}-${example.recommendation_id}`} example={example} />
          ))}
        </ul>
      )}
    </div>
  )
}

const LONG_EXCERPT = 240 // characters; longer excerpts start collapsed

function Excerpt({ example }: { example: TopicExample }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = example.excerpt.length > LONG_EXCERPT
  return (
    <li className="excerpt">
      <p className={isLong && !expanded ? 'review-text is-clamped' : 'review-text'}>“{example.excerpt}”</p>
      {isLong && (
        <button type="button" className="link-button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
      <p className="review-footer">
        {example.voted_up ? 'Recommended' : 'Not recommended'} · score {formatScore(example.sentiment_score)}
        {example.helpful_votes > 0 && <> · {formatCount(example.helpful_votes)} found helpful</>}
      </p>
    </li>
  )
}

function TopicTooltip({ active, payload }: TooltipContentProps) {
  if (!active || !payload?.length) return null
  const { label, mentionPct, summary } = payload[0].payload as Row
  return (
    <div className="tooltip">
      <strong>{label}</strong>
      <span>{formatCount(summary.mentions)} reviews mention it ({formatPct(mentionPct)})</span>
      <span>Praise {formatCount(summary.positive)} · Neutral {formatCount(summary.neutral)} · Complaints {formatCount(summary.negative)}</span>
    </div>
  )
}

function maxBy<T>(items: T[], value: (item: T) => number): T {
  return items.reduce((best, item) => (value(item) > value(best) ? item : best))
}

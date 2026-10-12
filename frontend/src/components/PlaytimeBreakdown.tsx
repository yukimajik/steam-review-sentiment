import type { Playtime, PlaytimeGroupStats } from '../api'
import { formatCount, formatPct, formatScore, PLAYTIME_LABELS, SENTIMENT_COLORS } from '../format'

// One row per playtime group, split like the rest of the page: the share who voted Not recommended
// to the left of the line, Recommended to the right. These are the players' own votes, not the model.
export function PlaytimeBreakdown({ data }: { data: Playtime }) {
  const description = data.groups
    .map((g) => `${PLAYTIME_LABELS[g.group]}: ${g.recommended_pct === null
      ? `${formatCount(g.recommended)} of ${formatCount(g.reviews)} recommended`
      : `${formatPct(g.recommended_pct)} recommended`}`)
    .join('; ')

  return (
    <section className="section">
      <div className="section-head">
        <h3>Playtime at review</h3>
        <p className="note">
          How many players recommend the game, grouped by how long they had played when they wrote their review. These
          are the players’ own votes, not the model. Under 2 hours is Steam’s refund window; Steam doesn’t say who
          refunded or finished the game. Groups with fewer than {data.min_reviews} reviews show counts instead of
          percentages.
        </p>
      </div>

      <div className="section-body">
        <ul className="topic-legend">
          <li><span className="swatch" style={{ background: SENTIMENT_COLORS.negative }} /> Not recommended</li>
          <li><span className="swatch" style={{ background: SENTIMENT_COLORS.positive }} /> Recommended</li>
        </ul>
        <ol className="playtime-rows" role="img" aria-label={`Share who recommend the game, by playtime. ${description}.`}>
          {data.groups.map((g) => <PlaytimeRow key={g.group} stats={g} />)}
        </ol>
        {data.unknown_playtime > 0 && (
          <p className="note">
            {formatCount(data.unknown_playtime)} {data.unknown_playtime === 1 ? 'review has' : 'reviews have'} no
            playtime from Steam and {data.unknown_playtime === 1 ? 'isn’t' : 'aren’t'} in any group.
          </p>
        )}

        <details className="data-table">
          <summary>Show data table</summary>
          <table>
            <thead>
              <tr>
                <th scope="col">Playtime</th><th scope="col">Reviews</th><th scope="col">Recommended</th>
                <th scope="col">% Recommended</th><th scope="col">Average model score</th>
              </tr>
            </thead>
            <tbody>
              {data.groups.map((g) => (
                <tr key={g.group}>
                  <td>{PLAYTIME_LABELS[g.group]}</td>
                  <td>{formatCount(g.reviews)}</td>
                  <td>{formatCount(g.recommended)}</td>
                  <td>{g.recommended_pct === null ? '–' : formatPct(g.recommended_pct)}</td>
                  <td>{g.avg_score === null ? '–' : formatScore(g.avg_score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </section>
  )
}

function PlaytimeRow({ stats }: { stats: PlaytimeGroupStats }) {
  const label = (
    <div className="playtime-label">
      <strong>{PLAYTIME_LABELS[stats.group]}</strong>
      <span>{formatCount(stats.reviews)} {stats.reviews === 1 ? 'review' : 'reviews'}</span>
    </div>
  )

  // Too few to compare: the raw count, with no bar that would look more precise than it is
  if (stats.recommended_pct === null) {
    return (
      <li className="playtime-row">
        {label}
        <p className="playtime-few">
          {stats.reviews === 0
            ? 'No reviews'
            : `${formatCount(stats.recommended)} of ${formatCount(stats.reviews)} recommended. Too few to compare.`}
        </p>
      </li>
    )
  }

  const notRecommended = 100 - stats.recommended_pct
  return (
    <li className="playtime-row">
      {label}
      <span className="playtime-pct is-negative">{formatPct(notRecommended)}</span>
      <span className="playtime-half is-negative">
        <span className="playtime-bar" style={{ width: `${notRecommended}%`, background: SENTIMENT_COLORS.negative }} />
      </span>
      <span className="playtime-half is-positive">
        <span className="playtime-bar" style={{ width: `${stats.recommended_pct}%`, background: SENTIMENT_COLORS.positive }} />
      </span>
      <span className="playtime-pct">{formatPct(stats.recommended_pct)}</span>
    </li>
  )
}

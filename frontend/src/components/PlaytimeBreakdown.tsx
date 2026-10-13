import type { Playtime, PlaytimeGroupStats } from '../api'
import { formatCount, formatPct, formatScore, PLAYTIME_LABELS, SENTIMENT_COLORS } from '../format'
import { useSeenOnce } from '../motion'
import type { ShowReviews } from './ReviewList'

// One row per playtime group, split like the rest of the page: the share who voted Not recommended
// to the left of the line, Recommended to the right. These are the players' own votes, not the model.
// Each half of a bar is a button that shows those reviews in the list below (`onShowReviews`).
export function PlaytimeBreakdown({ data, onShowReviews }: { data: Playtime; onShowReviews: ShowReviews }) {
  const [rowsRef, seen] = useSeenOnce<HTMLOListElement>() // the bars grow out from the line when first on screen

  return (
    <section className="section">
      <div className="section-head">
        <h3>Playtime at review</h3>
        <p className="note">
          How many players recommend the game, grouped by how long they had played when they wrote their review. These
          are the players’ own votes, not the model. Under 2 hours is Steam’s refund window; this page doesn’t show who
          actually refunded or finished the game. Groups with fewer than {data.min_reviews} reviews show counts instead
          of percentages. Click a bar to read those reviews.
        </p>
      </div>

      <div className="section-body">
        <ul className="topic-legend">
          <li><span className="swatch" style={{ background: SENTIMENT_COLORS.negative }} /> Not recommended</li>
          <li><span className="swatch" style={{ background: SENTIMENT_COLORS.positive }} /> Recommended</li>
        </ul>
        <ol ref={rowsRef} className={seen ? 'playtime-rows is-seen' : 'playtime-rows'} aria-label="Share who recommend the game, by playtime">
          {data.groups.map((g) => <PlaytimeRow key={g.group} stats={g} onShowReviews={onShowReviews} />)}
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

function PlaytimeRow({ stats, onShowReviews }: { stats: PlaytimeGroupStats; onShowReviews: ShowReviews }) {
  const played = PLAYTIME_LABELS[stats.group].toLowerCase() // "under 2 h"
  // The playtime button in the list covers the group; the vote has no button there, so it's the tag
  const showVote = (vote: 'up' | 'down') => onShowReviews({
    playtime: stats.group,
    scope: { vote },
    label: `Voted ${vote === 'up' ? 'Recommended' : 'Not recommended'}, from the playtime chart`,
  })
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
            : `${formatCount(stats.recommended)} of ${formatCount(stats.reviews)} recommended. Too few to compare. `}
          {stats.reviews > 0 && (
            <button type="button" className="link-button" onClick={() => onShowReviews({ playtime: stats.group })}>
              Read {stats.reviews === 1 ? 'it' : 'them'}
            </button>
          )}
        </p>
      </li>
    )
  }

  const notRecommended = 100 - stats.recommended_pct
  const notRecommendedCount = stats.reviews - stats.recommended
  return (
    <li className="playtime-row">
      {label}
      <span className="playtime-pct is-negative">{formatPct(notRecommended)}</span>
      <button type="button" className="playtime-half is-negative" onClick={() => showVote('down')}
        aria-label={`Read the ${formatCount(notRecommendedCount)} Not recommended reviews from players ${played}`}>
        <span className="playtime-bar" style={{ width: `${notRecommended}%`, background: SENTIMENT_COLORS.negative }} />
      </button>
      <button type="button" className="playtime-half is-positive" onClick={() => showVote('up')}
        aria-label={`Read the ${formatCount(stats.recommended)} Recommended reviews from players ${played}`}>
        <span className="playtime-bar" style={{ width: `${stats.recommended_pct}%`, background: SENTIMENT_COLORS.positive }} />
      </button>
      <span className="playtime-pct">{formatPct(stats.recommended_pct)}</span>
    </li>
  )
}

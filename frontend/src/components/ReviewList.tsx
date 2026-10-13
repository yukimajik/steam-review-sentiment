import { useEffect, useRef, useState, type CSSProperties } from 'react'
import {
  ApiError, getReviews, isAbort, type PlaytimeGroup, type ReviewPage, type Review, type ReviewScope, type Sentiment,
} from '../api'
import {
  formatCount, formatDate, formatPlaytime, formatScore, PLAYTIME_LABELS, SENTIMENT_COLORS, SENTIMENT_LABELS,
  stripFormatting,
} from '../format'

const PAGE_SIZE = 10
// Negative before positive, matching the left-to-right order used everywhere else
const FILTERS: { value: Sentiment | null; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'negative', label: 'Negative' },
  { value: 'neutral', label: 'Neutral' },
  { value: 'positive', label: 'Positive' },
]
const PLAYTIME_FILTERS: { value: PlaytimeGroup | null; label: string }[] = [
  { value: null, label: 'Any' },
  ...(Object.entries(PLAYTIME_LABELS) as [PlaytimeGroup, string][]).map(([value, label]) => ({ value, label })),
]

/** What a chart asks the review list to show: its sentiment and playtime buttons set to these, plus any
    filter the buttons can't express (`scope`), shown as a tag described by `label` that can be removed. */
export interface ReviewRequest {
  sentiment?: Sentiment | null
  playtime?: PlaytimeGroup | null
  scope?: ReviewScope
  label?: string // "September 2026 (Aug 31 – Sep 27, 2026), from the trend chart"
}

export type ShowReviews = (request: ReviewRequest) => void

// Rendered with a key per game and per chart request, so each starts fresh (filters and page reset).
export function ReviewList({ appId, request }: { appId: number; request: ReviewRequest | null }) {
  const [sentiment, setSentiment] = useState<Sentiment | null>(request?.sentiment ?? null)
  const [playtime, setPlaytime] = useState<PlaytimeGroup | null>(request?.playtime ?? null)
  const [scoped, setScoped] = useState(Boolean(request?.scope)) // until the chart's tag is removed
  const scope = scoped ? request?.scope ?? null : null
  const scopeLabel = scope ? request?.label ?? 'From a chart' : null
  const [page, setPage] = useState(1)
  const [retryCount, setRetryCount] = useState(0)
  // Results are tagged with the request they answer, so "loading" is simply
  // "the latest result isn't for the current request yet".
  const [loaded, setLoaded] = useState<{
    key: string; sentiment: Sentiment | null; playtime: PlaytimeGroup | null; data: ReviewPage
  } | null>(null)
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null)

  const requestKey = `${sentiment}-${playtime}-${scope !== null}-${page}-${retryCount}`
  const loading = loaded?.key !== requestKey && failed?.key !== requestKey
  const error = failed?.key === requestKey ? failed.message : null
  const data = loaded?.data ?? null // the previous page stays on screen (faded) while the next one loads

  useEffect(() => {
    const key = `${sentiment}-${playtime}-${scope !== null}-${page}-${retryCount}`
    const controller = new AbortController() // cancels this request if a filter or the page changes first
    getReviews(appId, sentiment, playtime, scope, page, PAGE_SIZE, controller.signal)
      .then((result) => setLoaded({ key, sentiment, playtime, data: result }))
      .catch((err) => {
        if (isAbort(err)) return
        setFailed({ key, message: err instanceof ApiError ? err.message : 'Could not load reviews.' })
      })
    return () => controller.abort()
  }, [appId, sentiment, playtime, scope, page, retryCount])

  // Opened from a chart: move keyboard focus here too, so the next Tab continues in the list
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (request) headingRef.current?.focus({ preventScroll: true })
  }, [request])

  function chooseSentiment(value: Sentiment | null) {
    setSentiment(value)
    setPage(1)
  }

  function choosePlaytime(value: PlaytimeGroup | null) {
    setPlaytime(value)
    setPage(1)
  }

  function removeScope() {
    setScoped(false)
    setPage(1)
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  // Describe the reviews on screen, which are for the last loaded filter
  const shownSentiment = loaded?.sentiment ?? null
  const shownPlaytime = loaded?.playtime ?? null
  const filterName = shownSentiment ? SENTIMENT_LABELS[shownSentiment].toLowerCase() + ' ' : ''
  const playtimeName = shownPlaytime ? `, ${PLAYTIME_LABELS[shownPlaytime].toLowerCase()} played` : '' // ", under 2 h played"

  return (
    <section className="section">
      <div className="section-head">
        <h3 ref={headingRef} tabIndex={-1}>Reviews</h3>
        {data && <p className="note">{formatCount(data.total)} {filterName}reviews{playtimeName}</p>}
        <p className="filter-label" id="sentiment-filter-label">Sentiment</p>
        <div className="filters" role="group" aria-labelledby="sentiment-filter-label">
          {FILTERS.map((filter) => (
            <button
              key={filter.label}
              type="button"
              className="filter"
              aria-pressed={sentiment === filter.value}
              onClick={() => chooseSentiment(filter.value)}
            >
              {filter.value && <span className="dot" style={{ background: SENTIMENT_COLORS[filter.value] }} />}
              {filter.label}
            </button>
          ))}
        </div>
        <p className="filter-label" id="playtime-filter-label">Playtime at review</p>
        <div className="filters" role="group" aria-labelledby="playtime-filter-label">
          {PLAYTIME_FILTERS.map((filter) => (
            <button
              key={filter.label}
              type="button"
              className="filter"
              aria-pressed={playtime === filter.value}
              onClick={() => choosePlaytime(filter.value)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        {scopeLabel && (
          <p className="review-scope">
            <span>{scopeLabel}</span>
            <button type="button" className="review-scope-remove" onClick={removeScope} aria-label={`Remove filter: ${scopeLabel}`}>
              <span aria-hidden="true">×</span>
            </button>
          </p>
        )}
      </div>

      <div className="section-body">
        {error ? (
          <div className="notice notice-error" role="alert">
            <p>{error}</p>
            <button type="button" className="button-secondary" onClick={() => setRetryCount((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : !data ? (
          <ReviewListSkeleton />
        ) : data.items.length === 0 ? (
          <p className="empty">
            No {filterName}reviews{playtimeName || (scopeLabel ? '' : ' for this game')}{scopeLabel && ' with the chart’s filter'}.
          </p>
        ) : (
          // While the next page loads, keep the current one visible but faded (no layout jump)
          <ol className={loading ? 'review-items is-refreshing' : 'review-items'} aria-busy={loading}>
            {data.items.map((review) => (
              <ReviewItem key={review.recommendation_id} review={review} />
            ))}
          </ol>
        )}

        {data && data.total > PAGE_SIZE && !error && (
          <nav className="pagination" aria-label="Review pages">
            <button type="button" className="button-secondary" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span>Page {formatCount(page)} of {formatCount(totalPages)}</span>
            <button type="button" className="button-secondary" disabled={page >= totalPages || loading} onClick={() => setPage(page + 1)}>
              Next
            </button>
          </nav>
        )}
      </div>
    </section>
  )
}

const LONG_REVIEW = 320 // characters; longer reviews start collapsed

function ReviewItem({ review }: { review: Review }) {
  const [expanded, setExpanded] = useState(false)
  const text = stripFormatting(review.review_text)
  const isLong = text.length > LONG_REVIEW
  const playtime = formatPlaytime(review.playtime_at_review_minutes)

  return (
    <li className="review" style={{ '--mark': SENTIMENT_COLORS[review.sentiment_label] } as CSSProperties}>
      <div className="review-meta">
        <span className="chip">
          <span className="dot" style={{ background: SENTIMENT_COLORS[review.sentiment_label] }} />
          {SENTIMENT_LABELS[review.sentiment_label]} <span className="chip-score">{formatScore(review.sentiment_compound)}</span>
        </span>
        <span className="vote">
          <ThumbIcon up={review.voted_up} />
          {review.voted_up ? 'Recommended' : 'Not recommended'}
        </span>
      </div>
      <p className={isLong && !expanded ? 'review-text is-clamped' : 'review-text'}>{text}</p>
      {isLong && (
        <button type="button" className="link-button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
      <p className="review-footer">
        {formatDate(review.created_at)}
        {playtime && <> · {playtime}</>}
      </p>
    </li>
  )
}

function ThumbIcon({ up }: { up: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" style={up ? undefined : { transform: 'scaleY(-1)' }}>
      <path
        d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3m0 11V11m0 11h10.3a2 2 0 0 0 2-1.7l1.4-9A2 2 0 0 0 18.7 9H14V5a3 3 0 0 0-3-3l-4 9"
        fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  )
}

function ReviewListSkeleton() {
  return (
    <ol className="review-items" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <li key={i} className="review">
          <div className="skeleton skeleton-text" style={{ width: '30%' }} />
          <div className="skeleton skeleton-text" />
          <div className="skeleton skeleton-text" style={{ width: '85%' }} />
        </li>
      ))}
    </ol>
  )
}

import { useEffect, useRef, useState } from 'react'
import { ApiError, fetchUpdateReviews, isAbort, type UpdateComparison, type Updates, type UpdateStatus } from '../api'
import { formatCount, formatDay, formatPct, formatScore, SENTIMENT_COLORS } from '../format'

const SECONDS_PER_UPDATE = 35 // measured: 28 requests to Steam take 33–36 s
const RATE_LIMIT_PAUSE_MS = 60_000 // Steam's limit lifted within about a minute and a half in a real run
const MAX_PAUSES = 5 // then give up and let the person try again later

const STATUS_NOTES: Record<UpdateStatus, string> = {
  ready: '',
  too_few_reviews: 'Too few reviews to rank',
  needs_reviews: 'Reviews not fetched yet',
  too_recent: 'The 2 weeks after aren’t over yet',
}

// Rendered with a key per game. `onFetched` reloads the dashboard once new reviews are stored.
export function UpdateShifts({ appId, data, onFetched }: { appId: number; data: Updates; onFetched: () => void }) {
  const [progress, setProgress] = useState<{ done: number; total: number; paused?: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [noneFound, setNoneFound] = useState(false)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => () => controller.current?.abort(), []) // leaving the game stops the fetching

  const waiting = data.updates.filter((u) => u.status === 'needs_reviews').length
  const ranked = data.updates.filter((u) => u.status === 'ready').length

  // One request per update, so the page can show progress and each request stays under a minute
  async function fetchAll() {
    const abort = new AbortController()
    controller.current = abort
    setError(null)
    setNoneFound(false)
    let done = 0
    let pauses = 0
    setProgress({ done, total: waiting })
    try {
      for (;;) {
        let result
        try {
          result = await fetchUpdateReviews(appId, abort.signal)
        } catch (err) {
          // Steam is rate limiting: wait, then carry on where it stopped (the days already fetched are saved)
          if (!(err instanceof ApiError && err.status === 429) || ++pauses > MAX_PAUSES) throw err
          setProgress((p) => p && { ...p, paused: true })
          await wait(RATE_LIMIT_PAUSE_MS, abort.signal)
          setProgress((p) => p && { ...p, paused: false })
          continue
        }
        pauses = 0
        if (result.fetched_day) done += 1
        setProgress({ done, total: done + result.remaining })
        if (result.updates_found === 0) {
          setNoneFound(true)
          setProgress(null)
          return
        }
        if (!result.fetched_day || result.remaining === 0) break
      }
      onFetched()
    } catch (err) {
      if (isAbort(err)) return
      setError(err instanceof ApiError ? err.message : 'Fetching reviews around updates failed.')
      setProgress(null)
    }
  }

  const minutes = Math.max(1, Math.round((waiting * SECONDS_PER_UPDATE) / 60))

  return (
    <section className="card updates">
      <h3>Sentiment around updates</h3>
      <p className="chart-note">
        Average model score in the {data.window_days} days before vs. the {data.window_days} days after each update
        from the last 12 months (the update’s own day is left out). This only compares before and after: sales, events,
        new seasons and new players arrive around the same time, so a shift doesn’t show that an update caused it.
      </p>

      {progress ? (
        <p className="notice-status" role="status">
          <span className="spinner" aria-hidden="true" />
          {progress.paused
            ? 'Steam asked us to slow down, so this is waiting a minute before continuing.'
            : progress.total > 0
              ? `Fetching reviews around update ${Math.min(progress.done + 1, progress.total)} of ${progress.total}…`
              : 'Checking Steam’s news for updates…'}{' '}
          Keep this tab open.
        </p>
      ) : data.updates.length === 0 ? (
        <div className="updates-action">
          <p>
            {noneFound
              ? 'No updates found in this game’s official Steam news from the last 12 months. Some developers name their updates in ways this check doesn’t recognize.'
              : 'Find this game’s updates in its official Steam news, then fetch the reviews from the 2 weeks before and after each one (about 35 seconds per update, up to 10 updates).'}
          </p>
          {!noneFound && <button type="button" className="button-primary" onClick={fetchAll}>Find updates</button>}
        </div>
      ) : waiting > 0 ? (
        <div className="updates-action">
          <p>
            {formatCount(waiting)} {waiting === 1 ? 'update needs' : 'updates need'} the reviews from around them. That
            takes about {minutes} {minutes === 1 ? 'minute' : 'minutes'}.
          </p>
          <button type="button" className="button-primary" onClick={fetchAll}>
            Fetch reviews around {waiting === 1 ? 'it' : `${formatCount(waiting)} updates`}
          </button>
        </div>
      ) : null}
      {error && (
        <p className="notice-error-text" role="alert">
          {error} Updates fetched before the error are kept; try again to continue.
        </p>
      )}

      {data.updates.length > 0 && (
        <>
          {ranked === 0 ? (
            !progress && waiting === 0 && (
              <p className="empty">
                No update has at least {data.min_reviews} reviews on each side yet, so none are ranked.
              </p>
            )
          ) : (
            <div className="shift-columns">
              <ShiftList kind="rises" items={data.biggest_rises} />
              <ShiftList kind="drops" items={data.biggest_drops} />
            </div>
          )}
          <details className="data-table">
            <summary>All updates ({formatCount(data.updates.length)})</summary>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Date</th><th scope="col">Update</th><th scope="col">Before</th>
                    <th scope="col">After</th><th scope="col">Change</th><th scope="col">Reviews</th><th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {data.updates.map((u) => (
                    <tr key={u.day}>
                      <td>{formatDay(u.day)}</td>
                      <td><UpdateTitle update={u} /></td>
                      <td>{scoreOrDash(u.before?.avg_score)}</td>
                      <td>{scoreOrDash(u.after?.avg_score)}</td>
                      <td>{scoreOrDash(u.shift)}</td>
                      <td>{u.before && u.after ? `${formatCount(u.before.reviews)} / ${formatCount(u.after.reviews)}` : '–'}</td>
                      <td>{STATUS_NOTES[u.status]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  )
}

function ShiftList({ kind, items }: { kind: 'rises' | 'drops'; items: UpdateComparison[] }) {
  const color = SENTIMENT_COLORS[kind === 'rises' ? 'positive' : 'negative']
  return (
    <div>
      <h4 className="topic-examples-title">
        <span className="dot" style={{ background: color }} />
        {kind === 'rises' ? 'Biggest rises' : 'Biggest drops'}
      </h4>
      {items.length === 0 ? (
        <p className="empty">No ranked update had a {kind === 'rises' ? 'higher' : 'lower'} average after.</p>
      ) : (
        <ol className="shifts">
          {items.map((u) => <ShiftItem key={u.day} update={u} color={color} />)}
        </ol>
      )}
    </div>
  )
}

function ShiftItem({ update, color }: { update: UpdateComparison; color: string }) {
  const { before, after, shift } = update
  // Ranked updates always have both sides; the check keeps TypeScript (and a surprise API answer) honest
  if (before?.avg_score == null || after?.avg_score == null || shift == null) return null
  return (
    <li className="shift">
      <p className="shift-title">
        <span className="shift-date">{formatDay(update.day)}</span> <UpdateTitle update={update} />
      </p>
      {/* 3 decimals: shifts are often small, and 2 would round before, after and change inconsistently */}
      <p>
        Average score {formatScore(before.avg_score, 3)} → {formatScore(after.avg_score, 3)}{' '}
        <strong style={{ color }}>({formatScore(shift, 3)})</strong>
      </p>
      <p className="review-footer">
        Recommended {formatPct(before.recommended_pct ?? 0)} → {formatPct(after.recommended_pct ?? 0)} ·{' '}
        {formatCount(before.reviews)} reviews before, {formatCount(after.reviews)} after
      </p>
    </li>
  )
}

function UpdateTitle({ update }: { update: UpdateComparison }) {
  const [first, ...more] = update.posts
  return (
    <>
      <a href={first.url} target="_blank" rel="noreferrer">{first.title}</a>
      {more.length > 0 && <span className="shift-more"> + {more.length} more {more.length === 1 ? 'post' : 'posts'}</span>}
    </>
  )
}

// 3 decimals: shifts are often small, and 2 would round before, after and change inconsistently
/** Resolves after `ms`, or rejects like a cancelled request if `signal` aborts first. */
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })
}

const scoreOrDash = (value: number | null | undefined) => (value == null ? '–' : formatScore(value, 3))

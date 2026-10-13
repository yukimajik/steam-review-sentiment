import { useEffect, useRef, useState } from 'react'
import { ApiError, fillTrendGaps, isAbort, wait } from '../api'
import { formatCount } from '../format'

const SECONDS_PER_WEEK = 1.5 // measured: 10 weeks took 14.3 s, scoring included
const RATE_LIMIT_PAUSE_MS = 60_000 // same pause as fetching around updates
const MAX_PAUSES = 5 // then give up and let the person try again later

// Rendered with a key per game. `weeks` is how many weeks of the past year under 30 reviews are still to fill;
// `onFilled` reloads the dashboard.
export function GapFill({ appId, weeks, onFilled }: { appId: number; weeks: number; onFilled: () => void }) {
  const [progress, setProgress] = useState<{ done: number; paused?: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => () => controller.current?.abort(), []) // leaving the game stops the filling

  // Up to 10 weeks per request, so the page can show progress and each request stays short
  async function fillAll() {
    const abort = new AbortController()
    controller.current = abort
    setError(null)
    let pauses = 0
    setProgress({ done: 0 })
    try {
      for (;;) {
        let result
        try {
          result = await fillTrendGaps(appId, abort.signal)
        } catch (err) {
          // Steam is rate limiting: wait, then carry on where it stopped (the weeks already filled are saved)
          if (!(err instanceof ApiError && err.status === 429) || ++pauses > MAX_PAUSES) throw err
          setProgress((p) => p && { ...p, paused: true })
          await wait(RATE_LIMIT_PAUSE_MS, abort.signal)
          setProgress((p) => p && { ...p, paused: false })
          continue
        }
        pauses = 0
        setProgress({ done: Math.max(0, weeks - result.remaining) })
        if (result.filled_weeks === 0 || result.remaining === 0) break
      }
      onFilled()
    } catch (err) {
      if (isAbort(err)) return
      setError(err instanceof ApiError ? err.message : 'Filling the weeks failed.')
      setProgress(null)
    }
  }

  const seconds = Math.max(10, Math.round((weeks * SECONDS_PER_WEEK) / 5) * 5)

  return (
    <div className="updates-action">
      {progress ? (
        <p className="notice-status" role="status">
          <span className="spinner" aria-hidden="true" />
          {progress.paused
            ? 'Steam asked us to slow down, so this is waiting a minute before continuing.'
            : `Filled ${formatCount(progress.done)} of ${formatCount(weeks)} weeks…`}{' '}
          Keep this tab open.
        </p>
      ) : (
        <>
          <p>
            The chart covers the past year, and {formatCount(weeks)} {weeks === 1 ? 'week' : 'weeks'} of it{' '}
            {weeks === 1 ? 'has' : 'have'} fewer than 30 stored reviews: a first fetch only gets the newest ones.
            Filling {weeks === 1 ? 'it' : 'them'} fetches a sample of each week, its newest 100 reviews, in about{' '}
            {seconds < 90 ? `${seconds} seconds` : `${Math.round(seconds / 60)} minutes`}.
          </p>
          <button type="button" className="button-primary" onClick={fillAll}>
            Fill {weeks === 1 ? 'the week' : `${formatCount(weeks)} weeks`}
          </button>
        </>
      )}
      {error && (
        <p className="notice-error-text" role="alert">
          {error} Weeks filled before the error are kept; try again to continue.
        </p>
      )}
    </div>
  )
}

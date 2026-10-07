import { useEffect, useState } from 'react'
import { ApiError, fetchFromSteam, getSummary, getTrend, isAbort, type Summary, type Trend } from './api'
import { ReviewList } from './components/ReviewList'
import { SearchForm } from './components/SearchForm'
import { SentimentPie } from './components/SentimentPie'
import { SummaryCards, SummaryCardsSkeleton } from './components/SummaryCards'
import { ChartSkeleton, TrendChart } from './components/TrendChart'
import { formatCount } from './format'

const FETCH_COUNT = 1000 // reviews to fetch when a game isn't stored yet

// The outcome of loading one game. `key` says which request it answers, so a result
// for an older request is never shown as the current one.
type Loaded = { key: string } & (
  | { status: 'ready'; summary: Summary; trend: Trend }
  | { status: 'not-stored' } // the API has no reviews for this game yet
  | { status: 'error'; message: string }
)

export default function App() {
  const [appId, setAppId] = useState<number | null>(null)
  const [reloadKey, setReloadKey] = useState(0) // bump to load the dashboard again
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [fetching, setFetching] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const requestKey = `${appId}-${reloadKey}`
  const dashboard = loaded?.key === requestKey ? loaded : null // null while the current request is loading

  useEffect(() => {
    if (appId === null) return
    const key = `${appId}-${reloadKey}`
    const controller = new AbortController() // a newer search cancels this one
    Promise.all([getSummary(appId, controller.signal), getTrend(appId, controller.signal)])
      .then(([summary, trend]) => setLoaded({ key, status: 'ready', summary, trend }))
      .catch((error) => {
        if (isAbort(error)) return
        if (error instanceof ApiError && error.status === 404) {
          setLoaded({ key, status: 'not-stored' })
        } else {
          const message = error instanceof ApiError ? error.message : 'Something went wrong.'
          setLoaded({ key, status: 'error', message })
        }
      })
    return () => controller.abort()
  }, [appId, reloadKey])

  function search(id: number) {
    setAppId(id)
    setFetchError(null)
    setReloadKey((key) => key + 1) // searching the same game again refreshes it
  }

  async function fetchReviews(id: number) {
    setFetching(true)
    setFetchError(null)
    try {
      await fetchFromSteam(id, FETCH_COUNT)
      setReloadKey((key) => key + 1)
    } catch (error) {
      setFetchError(error instanceof ApiError ? error.message : 'Fetching reviews failed.')
    } finally {
      setFetching(false)
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Steam Review Sentiment</h1>
        <p>How players feel about a game, from the text of their Steam reviews.</p>
      </header>

      {/* Disabled while fetching, so the result can't land on a different game */}
      <SearchForm onSearch={search} disabled={fetching} />

      <main>
        {appId === null ? (
          <p className="intro">Search for a game to see its sentiment breakdown, how it changed over time, and the reviews behind it.</p>
        ) : (
          <>
            <div className="dashboard-header">
              <h2>App {appId}</h2>
              <a href={`https://store.steampowered.com/app/${appId}`} target="_blank" rel="noreferrer">
                View on Steam ↗
              </a>
            </div>

            {dashboard === null && (
              <div className="dashboard" aria-busy="true">
                <p className="sr-only" role="status">Loading…</p>
                <SummaryCardsSkeleton />
                <div className="charts">
                  <ChartSkeleton title="Sentiment breakdown" />
                  <ChartSkeleton title="Average sentiment by month" />
                </div>
              </div>
            )}

            {dashboard?.status === 'not-stored' && (
              <div className="notice">
                <h3>No reviews stored for this game yet</h3>
                <p>
                  Fetch the {formatCount(FETCH_COUNT)} newest English reviews from Steam and score them. This takes about
                  10–15 seconds.
                </p>
                <button type="button" className="button-primary" disabled={fetching} onClick={() => fetchReviews(appId)}>
                  {fetching ? 'Fetching reviews…' : 'Fetch reviews from Steam'}
                </button>
                {fetching && (
                  <p className="notice-status" role="status">
                    <span className="spinner" aria-hidden="true" /> Downloading and scoring reviews. Keep this tab open.
                  </p>
                )}
                {fetchError && <p className="notice-error-text" role="alert">{fetchError}</p>}
              </div>
            )}

            {dashboard?.status === 'error' && (
              <div className="notice notice-error" role="alert">
                <p>{dashboard.message}</p>
                <button type="button" className="button-secondary" onClick={() => setReloadKey((key) => key + 1)}>
                  Try again
                </button>
              </div>
            )}

            {dashboard?.status === 'ready' && (
              <div className="dashboard">
                <SummaryCards summary={dashboard.summary} />
                <div className="charts">
                  <SentimentPie summary={dashboard.summary} />
                  <TrendChart months={dashboard.trend.months} />
                </div>
                <ReviewList key={appId} appId={appId} />
              </div>
            )}
          </>
        )}
      </main>

      <footer className="page-footer">
        Sentiment is scored by VADER, a word-based model. “Model agreement” is how often its label matches the player’s own
        thumbs up or down; neutral labels count as misses.
      </footer>
    </div>
  )
}

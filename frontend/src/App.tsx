import { useEffect, useState } from 'react'
import {
  ApiError, fetchFromSteam, getSummary, getTopics, getTrend, getUpdates, isAbort, type SearchResult, type Summary,
  type Topics, type Trend, type Updates,
} from './api'
import { ReviewList } from './components/ReviewList'
import { GameSearch } from './components/GameSearch'
import { SentimentPie } from './components/SentimentPie'
import { SummaryCards, SummaryCardsSkeleton } from './components/SummaryCards'
import { TopicBreakdown } from './components/TopicBreakdown'
import { ChartSkeleton, TrendChart } from './components/TrendChart'
import { UpdateShifts } from './components/UpdateShifts'
import { formatCount } from './format'

const FETCH_COUNT = 1000 // reviews to fetch when a game isn't stored yet
const SLOW_LOAD_MS = 5000 // after this long, explain that the server may be waking up

// The outcome of loading one game. `key` says which request it answers, so a result
// for an older request is never shown as the current one.
type Loaded = { key: string } & (
  | { status: 'ready'; summary: Summary; trend: Trend; topics: Topics; updates: Updates }
  | { status: 'not-stored' } // the API has no reviews for this game yet
  | { status: 'error'; message: string }
)

export default function App() {
  const [game, setGame] = useState<SearchResult | null>(null) // picked from the search box
  const appId = game?.app_id ?? null
  const [reloadKey, setReloadKey] = useState(0) // bump to load the dashboard again
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [fetching, setFetching] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [slowKey, setSlowKey] = useState<string | null>(null) // the request that's taking a while

  const requestKey = `${appId}-${reloadKey}`
  const dashboard = loaded?.key === requestKey ? loaded : null // null while the current request is loading

  useEffect(() => {
    if (appId === null) return
    const key = `${appId}-${reloadKey}`
    const controller = new AbortController() // a newer search cancels this one
    const { signal } = controller
    Promise.all([getSummary(appId, signal), getTrend(appId, signal), getTopics(appId, signal), getUpdates(appId, signal)])
      .then(([summary, trend, topics, updates]) => setLoaded({ key, status: 'ready', summary, trend, topics, updates }))
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

  // The free hosting plan puts the API to sleep when nobody uses it; the first request
  // then waits for it to wake. Explain the wait instead of showing placeholders silently.
  const isSlow = dashboard === null && slowKey === requestKey
  useEffect(() => {
    if (appId === null || dashboard !== null) return
    const timer = setTimeout(() => setSlowKey(requestKey), SLOW_LOAD_MS)
    return () => clearTimeout(timer)
  }, [appId, dashboard, requestKey])

  function pickGame(picked: SearchResult) {
    setGame(picked)
    setFetchError(null)
    setReloadKey((key) => key + 1) // picking the same game again refreshes it
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
      <GameSearch onSelect={pickGame} disabled={fetching} />

      <main>
        {game === null || appId === null ? (
          <p className="intro">Search for a game to see its sentiment breakdown, how it changed over time, and the reviews behind it.</p>
        ) : (
          <>
            <div className="dashboard-header">
              <div className="game-title">
                {game.image_url && <img src={game.image_url} alt="" width={116} height={44} />}
                <div>
                  <h2>{game.name}</h2>
                  <p className="game-id">App {appId}</p>
                </div>
              </div>
              <a href={`https://store.steampowered.com/app/${appId}`} target="_blank" rel="noreferrer">
                View on Steam ↗
              </a>
            </div>

            {dashboard === null && (
              <div className="dashboard" aria-busy="true">
                <p className="sr-only" role="status">Loading…</p>
                {isSlow && (
                  <p className="loading-note" role="status">
                    <span className="spinner" aria-hidden="true" /> Still loading. The server sleeps after a while
                    without visitors and can take up to a minute to wake up.
                  </p>
                )}
                <SummaryCardsSkeleton />
                <div className="charts">
                  <ChartSkeleton title="Sentiment breakdown" />
                  <ChartSkeleton title="Average sentiment by week" />
                </div>
                <ChartSkeleton title="Sentiment around updates" />
                <ChartSkeleton title="What players talk about" />
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
                  <TrendChart
                    weeks={dashboard.trend.weeks}
                    updateTimes={dashboard.updates.updates.map((u) => Date.parse(u.posts[0].posted_at))}
                  />
                </div>
                <UpdateShifts
                  key={`updates-${appId}`}
                  appId={appId}
                  data={dashboard.updates}
                  onFetched={() => setReloadKey((key) => key + 1)}
                />
                {/* Its key must differ from ReviewList's: siblings can't share one */}
                <TopicBreakdown key={`topics-${appId}`} data={dashboard.topics} />
                <ReviewList key={appId} appId={appId} />
              </div>
            )}
          </>
        )}
      </main>

      <footer className="page-footer">
        Sentiment labels come from a classifier (TF-IDF + logistic regression) trained on Steam reviews to predict whether
        the player recommends the game; “neutral” means it isn’t confident either way. “Model agreement” is how often its
        label matches the player’s own thumbs up or down, with neutral counting as a miss. Topics are found with keyword
        lists, so reviews that describe a topic in other words are missed; each topic’s praise or complaint comes from
        the model scoring only the sentences about it. Updates come from each game’s official Steam news; the before/after
        numbers are comparisons, not proof that an update changed anything.
      </footer>
    </div>
  )
}

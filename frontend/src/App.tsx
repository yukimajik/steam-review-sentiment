import { useEffect, useState, type MouseEvent } from 'react'
import {
  ApiError, fetchFromSteam, getDetails, getPlaytime, getSummary, getTopics, getTrend, getUpdates, isAbort, type Playtime,
  type SearchResult, type Summary, type Topics, type Trend, type Updates,
} from './api'
import { GameHero, SplitMark } from './components/GameHero'
import { GameSearch } from './components/GameSearch'
import { PlaytimeBreakdown } from './components/PlaytimeBreakdown'
import { ReviewList } from './components/ReviewList'
import { SentimentSplit, SentimentSplitSkeleton } from './components/SentimentSplit'
import { TopicBreakdown } from './components/TopicBreakdown'
import { ChartSkeleton, TrendChart } from './components/TrendChart'
import { UpdateShifts } from './components/UpdateShifts'
import { SectionNav } from './components/SectionNav'
import { HomeShowcase } from './components/HomeShowcase'
import { ThemeToggle } from './components/ThemeToggle'
import { formatCount } from './format'
import { appIdFromPath, gamePath } from './route'

const APP_NAME = 'SteamView' // a working name; also the page title in index.html
const FETCH_COUNT = 1000 // reviews to fetch when a game isn't stored yet
const SLOW_LOAD_MS = 5000 // after this long, explain that the server may be waking up

// The outcome of loading one game. `key` says which request it answers, so a result
// for an older request is never shown as the current one.
type Loaded = { key: string } & (
  | { status: 'ready'; summary: Summary; trend: Trend; topics: Topics; updates: Updates; playtime: Playtime }
  | { status: 'not-stored' } // the API has no reviews for this game yet
  | { status: 'error'; message: string }
)

// What's known about the open game's name and cover. Picking a game from the search or the shelf
// brings them along; opening a game from its web address looks them up.
type Details = { appId: number } & (
  | { status: 'ready'; game: SearchResult }
  | { status: 'no-page' } // Steam has no store page for this ID
  | { status: 'failed' } // the lookup failed; the dashboard still loads, under "App 570"
)

// Moves to another page of the app with a new entry in the browser's history, so Back returns here
function navigate(path: string) {
  if (path !== window.location.pathname) window.history.pushState(null, '', path)
}

export default function App() {
  // The open game comes from the web address ("/game/570/dota-2"); null on the front page
  const [appId, setAppId] = useState(() => appIdFromPath(window.location.pathname))
  const [details, setDetails] = useState<Details | null>(null)
  const [reloadKey, setReloadKey] = useState(0) // bump to load the dashboard again
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [fetching, setFetching] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [slowKey, setSlowKey] = useState<string | null>(null) // the request that's taking a while

  const known = details?.appId === appId ? details : null // null while the name is looked up
  const game: SearchResult | null = appId === null || known === null ? null
    : known.status === 'ready' ? known.game : { app_id: appId, name: `App ${appId}`, image_url: null }

  const requestKey = `${appId}-${reloadKey}`
  const dashboard = loaded?.key === requestKey ? loaded : null // null while the current request is loading

  useEffect(() => {
    if (appId === null) return
    const key = `${appId}-${reloadKey}`
    const controller = new AbortController() // a newer search cancels this one
    const { signal } = controller
    Promise.all([
      getSummary(appId, signal), getTrend(appId, signal), getTopics(appId, signal), getUpdates(appId, signal),
      getPlaytime(appId, signal),
    ])
      .then(([summary, trend, topics, updates, playtime]) =>
        setLoaded({ key, status: 'ready', summary, trend, topics, updates, playtime }))
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

  // Back and Forward change the address without reloading the page; follow them
  useEffect(() => {
    const follow = () => {
      setAppId(appIdFromPath(window.location.pathname))
      setFetchError(null)
    }
    window.addEventListener('popstate', follow)
    return () => window.removeEventListener('popstate', follow)
  }, [])

  // Look up the name and cover of a game opened from its address
  const knownId = details?.appId
  useEffect(() => {
    if (appId === null || knownId === appId) return
    const controller = new AbortController()
    getDetails(appId, controller.signal)
      .then((found) => setDetails({ appId, status: 'ready', game: found }))
      .catch((error) => {
        if (isAbort(error)) return
        const noPage = error instanceof ApiError && error.status === 404
        setDetails({ appId, status: noPage ? 'no-page' : 'failed' })
      })
    return () => controller.abort()
  }, [appId, knownId])

  // Keep the address tidy: a game's address carries its current name (a pasted link may have an old one
  // or none), and an address that isn't a page of the app becomes the front page's. Replaces, so Back
  // doesn't step through the untidy version.
  const tidyPath = appId === null ? '/' : known?.status === 'ready' ? gamePath(appId, known.game.name) : null
  useEffect(() => {
    if (tidyPath !== null && tidyPath !== window.location.pathname) window.history.replaceState(null, '', tidyPath)
  }, [tidyPath])

  const gameName = game?.name
  useEffect(() => {
    document.title = gameName ? `${gameName} · ${APP_NAME}` : APP_NAME
  }, [gameName])

  // The free hosting plan puts the API to sleep when nobody uses it; the first request
  // then waits for it to wake. Explain the wait instead of showing placeholders silently.
  const isSlow = dashboard === null && slowKey === requestKey
  useEffect(() => {
    if (appId === null || dashboard !== null) return
    const timer = setTimeout(() => setSlowKey(requestKey), SLOW_LOAD_MS)
    return () => clearTimeout(timer)
  }, [appId, dashboard, requestKey])

  function pickGame(picked: SearchResult) {
    setDetails({ appId: picked.app_id, status: 'ready', game: picked })
    setAppId(picked.app_id)
    navigate(gamePath(picked.app_id, picked.name))
    setFetchError(null)
    setReloadKey((key) => key + 1) // picking the same game again refreshes it
  }

  // The title is a link to the front page. A plain click switches pages here; a click meant to open a
  // new tab or window (middle click, ⌘ or Ctrl) is left to the browser.
  function goHome(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate('/')
    setAppId(null)
    window.scrollTo({ top: 0, behavior: 'instant' })
  }

  function tryAgain() {
    if (known?.status === 'failed') setDetails(null) // look the name up again too
    setReloadKey((key) => key + 1)
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
    // On the start page the title and search are large; once a game is picked they shrink into a bar
    <div className={appId === null ? 'page is-home' : 'page'}>
      <header className="masthead">
        <a className="brand" href="/" onClick={goHome}>
          <SplitMark />
          <div>
            <h1>{APP_NAME}</h1>
            <p className="tagline">How players feel about a game, from what they write in their Steam reviews.</p>
          </div>
        </a>
        {/* Disabled while fetching, so the result can't land on a different game */}
        <GameSearch onSelect={pickGame} disabled={fetching} />
        <ThemeToggle />
        {dashboard?.status === 'ready' && <SectionNav />}
      </header>

      <main>
        {appId === null ? (
          <HomeShowcase onPick={pickGame} />
        ) : (
          <>
            {/* The ids are what the section links in the bar scroll to */}
            <div id="overview" className="anchor">
              <GameHero appId={appId} game={game}>
                {dashboard === null && <SentimentSplitSkeleton />}
                {dashboard?.status === 'ready' && <SentimentSplit summary={dashboard.summary} />}
              </GameHero>
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
                <ChartSkeleton title="Average sentiment by week" />
                <ChartSkeleton title="Playtime at review" />
                <ChartSkeleton title="Sentiment around updates" />
                <ChartSkeleton title="What players talk about" />
              </div>
            )}

            {dashboard?.status === 'not-stored' && known?.status === 'no-page' && (
              <div className="notice">
                <h3>No game found</h3>
                <p>Steam has no store page for app {appId}. The link may be wrong, or the game was removed.</p>
                <a className="button-secondary" href="/" onClick={goHome}>Go to the front page</a>
              </div>
            )}

            {dashboard?.status === 'not-stored' && known !== null && known.status !== 'no-page' && (
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
                <button type="button" className="button-secondary" onClick={tryAgain}>
                  Try again
                </button>
              </div>
            )}

            {dashboard?.status === 'ready' && (
              <div className="dashboard">
                <div id="trend" className="anchor">
                  <TrendChart
                    appId={appId}
                    months={dashboard.trend.months}
                    updateTimes={dashboard.updates.updates.map((u) => Date.parse(u.posts[0].posted_at))}
                    weeksToFill={dashboard.trend.weeks_to_fill}
                    onFilled={() => setReloadKey((key) => key + 1)}
                  />
                </div>
                <div id="playtime" className="anchor">
                  <PlaytimeBreakdown data={dashboard.playtime} />
                </div>
                <div id="updates" className="anchor">
                  <UpdateShifts
                    key={`updates-${appId}`}
                    appId={appId}
                    data={dashboard.updates}
                    onFetched={() => setReloadKey((key) => key + 1)}
                  />
                </div>
                <div id="topics" className="anchor">
                  <TopicBreakdown key={`topics-${appId}`} data={dashboard.topics} />
                </div>
                <div id="reviews" className="anchor">
                  <ReviewList key={appId} appId={appId} />
                </div>
              </div>
            )}
          </>
        )}
      </main>

      <footer className="page-footer">
        {/* On the front page the method notes fold away; on a dashboard they stay open */}
        {appId === null ? (
          <details>
            <summary>How the numbers work</summary>
            <MethodNotes />
          </details>
        ) : (
          <MethodNotes />
        )}
      </footer>
    </div>
  )
}

function MethodNotes() {
  return (
    <p>
      Sentiment labels come from a classifier (TF-IDF + logistic regression) trained on Steam reviews to predict
      whether the player recommends the game; “neutral” means it isn’t confident either way. “Model agreement” is how
      often its label matches the player’s own thumbs up or down, with neutral counting as a miss. Topics are found
      with keyword lists, so reviews that describe a topic in other words are missed; each topic’s praise or
      complaint comes from the model scoring only the sentences about it. Updates come from each game’s official
      Steam news; the before/after numbers are comparisons, not proof that an update changed anything.
    </p>
  )
}

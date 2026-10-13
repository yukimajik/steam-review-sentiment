import { useEffect, useState, type CSSProperties } from 'react'
import { flushSync } from 'react-dom'
import { getGames, isAbort, type SearchResult, type StoredGame, type StoredGames } from '../api'
import { formatCount, formatPct, SENTIMENT_COLORS } from '../format'
import { usePrefersReducedMotion } from '../motion'
import { CountUp } from './CountUp'

const WALL_SIZE = 48 // covers in the background collage; stored games repeat to fill it
const formatWhole = (n: number) => formatCount(Math.round(n))

// The front page under the search: a collage of stored games' covers behind everything, and a shelf
// of those games to open with one click. Hovering a cover washes the page in that game's art.
export function HomeShowcase({ onPick }: { onPick: (game: SearchResult) => void }) {
  const [state, setState] = useState<StoredGames | 'loading' | 'failed'>('loading')
  const [focusArt, setFocusArt] = useState<string | null>(null) // the hovered cover
  const reduced = usePrefersReducedMotion()

  // Opening a game from the shelf: its cover moves into the dashboard header's cover spot while the
  // rest of the page cross-fades (the View Transitions API). Browsers without it, and people who ask
  // for reduced motion, get the dashboard straight away.
  function open(game: StoredGame, cover: HTMLImageElement | null) {
    const show = () => {
      onPick({ app_id: game.app_id, name: game.name ?? `App ${game.app_id}`, image_url: game.image_url })
      window.scrollTo({ top: 0, behavior: 'instant' }) // the dashboard starts at its top, wherever the shelf was
    }
    if (reduced || !cover || !document.startViewTransition) {
      show()
      return
    }
    cover.style.viewTransitionName = 'game-cover' // only the clicked cover takes part
    document.startViewTransition(() => flushSync(show))
  }

  useEffect(() => {
    const controller = new AbortController()
    getGames(controller.signal)
      .then(setState)
      .catch((error) => {
        if (!isAbort(error)) setState('failed')
      })
    return () => controller.abort()
  }, [])

  // Nothing stored yet, or the API can't be reached: the search still works, so describe the app instead
  if (state === 'failed' || (state !== 'loading' && state.games.length === 0)) {
    return (
      <p className="intro">
        Pick a game to see how its reviews split between positive and negative, how that changed week by week and
        around updates, how it differs by playtime, what players praise and complain about, and the reviews behind it.
      </p>
    )
  }

  const games = state === 'loading' ? [] : state.games
  const wall = games.length ? Array.from({ length: WALL_SIZE }, (_, i) => games[i % games.length]) : []

  return (
    <>
      <div className="home-art" aria-hidden="true">
        <div className={wall.length ? 'collage is-ready' : 'collage'}>
          {wall.map((game, i) => <img key={i} src={game.image_url} alt="" decoding="async" />)}
        </div>
        <div
          className={focusArt ? 'focus-art is-on' : 'focus-art'}
          style={focusArt ? ({ '--art': `url("${focusArt}")` } as CSSProperties) : undefined}
        />
        <div className="home-veil" />
      </div>

      <section className="shelf" aria-labelledby="shelf-title" aria-busy={state === 'loading'}>
        <div className="shelf-head">
          <h2 id="shelf-title">Already analyzed</h2>
          {state !== 'loading' && (
            <p>
              <CountUp value={state.total_reviews} format={formatWhole} /> reviews read across{' '}
              {formatCount(games.length)} {games.length === 1 ? 'game' : 'games'}
            </p>
          )}
        </div>
        <ul className="shelf-cards">
          {state === 'loading'
            ? Array.from({ length: 5 }, (_, i) => <li key={i} className="shelf-card" aria-hidden="true"><div className="skeleton shelf-cover" /></li>)
            : games.map((game) => (
              <li key={game.app_id} className="shelf-card">
                <ShelfCard
                  game={game}
                  onOpen={(cover) => open(game, cover)}
                  onFocus={() => setFocusArt(game.image_url)}
                  onBlur={() => setFocusArt(null)}
                />
              </li>
            ))}
        </ul>
      </section>
    </>
  )
}

function ShelfCard({ game, onOpen, onFocus, onBlur }: {
  game: StoredGame
  onOpen: (cover: HTMLImageElement | null) => void
  onFocus: () => void
  onBlur: () => void
}) {
  const name = game.name ?? `App ${game.app_id}`
  return (
    <button
      type="button"
      className="shelf-button"
      onClick={(event) => onOpen(event.currentTarget.querySelector('img'))}
      onMouseEnter={onFocus}
      onMouseLeave={onBlur}
      onFocus={onFocus}
      onBlur={onBlur}
    >
      <img className="shelf-cover" src={game.image_url} alt="" loading="lazy" decoding="async" />
      {/* Negative | neutral | positive, the same order as everywhere else */}
      <span className="shelf-split" aria-hidden="true">
        <span style={{ flexGrow: game.negative_pct, background: SENTIMENT_COLORS.negative }} />
        <span className="is-neutral" style={{ flexGrow: game.neutral_pct, background: SENTIMENT_COLORS.neutral }} />
        <span style={{ flexGrow: game.positive_pct, background: SENTIMENT_COLORS.positive }} />
      </span>
      <span className="shelf-name">{name}</span>
      <span className="shelf-meta">
        <span>{formatPct(game.negative_pct)} negative</span>
        <span>{formatPct(game.positive_pct)} positive</span>
      </span>
    </button>
  )
}

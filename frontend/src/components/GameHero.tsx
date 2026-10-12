import type { CSSProperties, ReactNode } from 'react'
import type { SearchResult } from '../api'

// The top of a game's dashboard: its cover, name and Steam link. The cover is also blurred
// behind the header, so each game's page takes on a little of its own colors.
export function GameHero({ game, children }: { game: SearchResult; children: ReactNode }) {
  const art = game.image_url ? ({ '--art': `url(${JSON.stringify(game.image_url)})` } as CSSProperties) : undefined
  return (
    <section className="hero" style={art} aria-labelledby="game-name">
      <div className="hero-head">
        {game.image_url && <img src={game.image_url} alt="" width={184} height={69} />}
        <div className="hero-title">
          <h2 id="game-name">{game.name}</h2>
          <p className="game-id">App {game.app_id}</p>
        </div>
        <a className="hero-link" href={`https://store.steampowered.com/app/${game.app_id}`} target="_blank" rel="noreferrer">
          View on Steam ↗
        </a>
      </div>
      {children}
    </section>
  )
}

/** The logo: a ring split at the top, negative on the left and positive on the right, like the donut. */
export function SplitMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M14.4 4.1 A12 12 0 0 0 14.4 27.9" stroke="var(--sentiment-negative)" strokeWidth="6" fill="none" />
      <path d="M17.6 4.1 A12 12 0 0 1 17.6 27.9" stroke="var(--sentiment-positive)" strokeWidth="6" fill="none" />
    </svg>
  )
}

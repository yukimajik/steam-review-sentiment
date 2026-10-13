import type { CSSProperties, ReactNode } from 'react'
import type { SearchResult } from '../api'

// The top of a game's dashboard: its cover, name and Steam link. The cover is also blurred into a
// wash across the top of the page, like the background art on a Steam store page, and into a much
// fainter tint that stays behind the whole page as it scrolls, so each game's page keeps its colors.
// `game` is null while its name and cover are looked up (a dashboard opened from its web address).
export function GameHero({ appId, game, children }: { appId: number; game: SearchResult | null; children: ReactNode }) {
  const art = game?.image_url ? ({ '--art': `url(${JSON.stringify(game.image_url)})` } as CSSProperties) : undefined
  return (
    <>
      {art && <div className="page-ambient" style={art} aria-hidden="true" />}
      {art && <div className="page-art" style={art} aria-hidden="true" />}
      <section className="hero" aria-labelledby="game-name">
        <div className="hero-head">
          {/* hero-cover: a cover clicked on the front page's shelf moves into this spot (index.css) */}
          {game?.image_url && <img className="hero-cover" src={game.image_url} alt="" width={184} height={69} />}
          <div className="hero-title">
            {game ? (
              <h2 id="game-name">{game.name}</h2>
            ) : (
              <div id="game-name" className="skeleton hero-name-skeleton" aria-label={`App ${appId}`} />
            )}
            <p className="game-id">App {appId}</p>
          </div>
          <a className="hero-link" href={`https://store.steampowered.com/app/${appId}`} target="_blank" rel="noreferrer">
            View on Steam ↗
          </a>
        </div>
        {children}
      </section>
    </>
  )
}

/** The logo: a classic yin-yang in the page's own ink and panel colors (so it flips with the theme),
    with the two sentiments only in the dots: negative in the light half, positive in the dark one. */
export function SplitMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="15" fill="var(--panel)" stroke="var(--ink)" strokeWidth="1.2" />
      {/* Right half, with the S-curve: its top bulges right, its bottom bulges left */}
      <path d="M16 1 A15 15 0 0 1 16 31 A7.5 7.5 0 0 1 16 16 A7.5 7.5 0 0 0 16 1 Z" fill="var(--ink)" />
      <circle cx="16" cy="8.5" r="2.6" fill="var(--sentiment-negative)" />
      <circle cx="16" cy="23.5" r="2.6" fill="var(--sentiment-positive)" />
    </svg>
  )
}

import { useEffect, useId, useState, type KeyboardEvent } from 'react'
import { ApiError, isAbort, searchGames, type SearchResponse, type SearchResult } from '../api'

const DEBOUNCE_MS = 300 // search once typing pauses, not on every keystroke
const MIN_CHARS = 2

interface Props {
  onSelect: (game: SearchResult) => void
  disabled?: boolean
}

// Lowercase and single spaces, like the backend, so "Portal " and "portal" are one search
const clean = (text: string) => text.trim().replace(/\s+/g, ' ').toLowerCase()

/** A search box with a dropdown of matching games (an accessible "combobox"). */
export function GameSearch({ onSelect, disabled }: Props) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1) // option highlighted with the arrow keys
  // The latest answer, tagged with the query it answers, so an old answer is never taken for the current one
  const [answer, setAnswer] = useState<{ query: string; data?: SearchResponse; error?: string } | null>(null)
  const listId = useId()

  const query = clean(text)
  const tooShort = query.length < MIN_CHARS
  const current = answer?.query === query ? answer : null
  const needsSearch = open && !tooShort && current === null
  // While the next search runs, keep showing the previous results (faded) instead of flashing empty
  const shown = current ?? answer
  const results = shown?.data?.results ?? []
  const stale = current === null

  useEffect(() => {
    if (!needsSearch) return
    const controller = new AbortController() // typing again cancels a search that's already running
    const timer = setTimeout(() => {
      searchGames(query, controller.signal)
        .then((data) => setAnswer({ query, data }))
        .catch((error) => {
          if (isAbort(error)) return
          setAnswer({ query, error: error instanceof ApiError ? error.message : 'Search failed.' })
        })
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, needsSearch])

  function choose(game: SearchResult) {
    setText(game.name)
    setOpen(false)
    setActiveIndex(-1)
    onSelect(game)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && results.length) {
      event.preventDefault()
      setOpen(true)
      setActiveIndex((i) => (i + 1) % results.length)
    } else if (event.key === 'ArrowUp' && results.length) {
      event.preventDefault()
      setActiveIndex((i) => (i <= 0 ? results.length - 1 : i - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      // Enter picks the highlighted game, or the top match if the results are for what's typed now
      const pick = results[activeIndex] ?? (stale ? undefined : results[0])
      if (pick) choose(pick)
    } else if (event.key === 'Escape') {
      setOpen(false)
      setActiveIndex(-1)
    }
  }

  const showPopup = open && !tooShort
  const trimmedTypo = shown?.data && shown.data.matched_query !== shown.data.query && results.length > 0

  return (
    <div className="search">
      <label htmlFor="game-search">Search for a game</label>
      <div className="game-search">
        <input
          id="game-search"
          type="text"
          role="combobox"
          aria-expanded={showPopup}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showPopup && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
          aria-describedby="game-search-help"
          autoComplete="off"
          spellCheck={false}
          placeholder="e.g. Hollow Knight"
          value={text}
          disabled={disabled}
          onChange={(event) => {
            setText(event.target.value)
            setOpen(true)
            setActiveIndex(-1)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={handleKeyDown}
        />

        {showPopup && (
          // preventDefault keeps focus in the input, so clicking an option doesn't close the list first
          <div className="search-popup" onMouseDown={(event) => event.preventDefault()}>
            {shown?.error && !stale ? (
              <p className="search-status search-error">{shown.error}</p>
            ) : shown?.data && !stale && results.length === 0 ? (
              <p className="search-status">
                No games match “{shown.data.query}”. Check the spelling, or type just the start of the name.
              </p>
            ) : (
              <>
                {stale && <p className="search-status"><span className="spinner" aria-hidden="true" /> Searching…</p>}
                {trimmedTypo && (
                  <p className="search-status">
                    No exact match for “{shown.data!.query}”. Showing results for “{shown.data!.matched_query}”.
                  </p>
                )}
              </>
            )}
            <ul id={listId} role="listbox" aria-label="Matching games" className={stale ? 'search-results is-stale' : 'search-results'}>
              {results.map((game, i) => (
                <li
                  key={game.app_id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === activeIndex}
                  className={i === activeIndex ? 'search-option is-active' : 'search-option'}
                  onClick={() => choose(game)}
                  onMouseMove={() => setActiveIndex(i)}
                >
                  {game.image_url ? (
                    <img src={game.image_url} alt="" width={92} height={35} loading="lazy" />
                  ) : (
                    <span className="cover-placeholder" aria-hidden="true" />
                  )}
                  <span className="search-option-name">{game.name}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <p id="game-search-help" className="field-help">
        Results appear as you type. Pick a game to see its reviews.
      </p>
      {/* Read out by screen readers when the results change */}
      <p className="sr-only" role="status">
        {showPopup && !stale ? (shown?.error ?? `${results.length} games found`) : ''}
      </p>
    </div>
  )
}

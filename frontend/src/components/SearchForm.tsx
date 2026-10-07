import { useState, type FormEvent } from 'react'

const MAX_APP_ID = 2 ** 31 - 1 // the API stores app IDs as a PostgreSQL INTEGER

interface Props {
  onSearch: (appId: number) => void
  disabled?: boolean
}

export function SearchForm({ onSearch, disabled }: Props) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmed = value.trim()
    const appId = Number(trimmed)
    // Check before calling the API, so a typo gets an instant, specific message
    if (!/^\d+$/.test(trimmed) || appId < 1 || appId > MAX_APP_ID) {
      setError('Enter a Steam app ID: a whole number like 620.')
      return
    }
    setError(null)
    onSearch(appId)
  }

  return (
    <form className="search" onSubmit={handleSubmit} noValidate>
      <label htmlFor="app-id">Steam app ID</label>
      <div className="search-row">
        <input
          id="app-id"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          placeholder="e.g. 620"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby="app-id-help"
        />
        <button type="submit" className="button-primary" disabled={disabled}>
          Search
        </button>
      </div>
      <p id="app-id-help" className={error ? 'field-error' : 'field-help'} role={error ? 'alert' : undefined}>
        {error ?? 'The number in a game’s store URL, e.g. store.steampowered.com/app/620 is Portal 2.'}
      </p>
    </form>
  )
}

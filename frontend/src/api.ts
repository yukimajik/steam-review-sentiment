// Talks to the FastAPI backend. Types mirror the API's response models.

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Sentiment = 'positive' | 'neutral' | 'negative'

export interface Summary {
  app_id: number
  total_reviews: number
  positive_pct: number
  neutral_pct: number
  negative_pct: number
  agreement_pct: number // the model's label matches the player's vote; neutral counts as a miss
  baseline_pct: number // what always guessing the more common vote would score
}

export interface TrendMonth {
  month: string // "2026-08"
  avg_compound: number // -1 to +1
  review_count: number
}

export interface Trend {
  app_id: number
  months: TrendMonth[]
}

export interface Review {
  recommendation_id: number
  review_text: string
  voted_up: boolean
  sentiment_label: Sentiment
  sentiment_compound: number
  playtime_at_review_minutes: number | null
  helpful_votes: number
  created_at: string
}

export interface ReviewPage {
  app_id: number
  page: number
  page_size: number
  total: number
  items: Review[]
}

export interface SearchResult {
  app_id: number
  name: string
  image_url: string | null // small cover image on Steam's servers
}

export interface SearchResponse {
  query: string // what was searched for, cleaned up
  matched_query: string // what produced the results; shorter than `query` when a typo was trimmed
  results: SearchResult[]
}

export interface FetchResult {
  app_id: number
  fetched: number
  new: number
  scored: number
}

/** An error to show the user. `status` is the HTTP status, or null if the API couldn't be reached. */
export class ApiError extends Error {
  status: number | null

  constructor(status: number | null, message: string) {
    super(message)
    this.status = status
  }
}

function messageFor(status: number, detail: unknown): string {
  switch (status) {
    case 404:
      return typeof detail === 'string' ? detail : 'Not found.'
    case 422:
      return typeof detail === 'string' ? detail : "That isn't a valid request."
    case 502:
      return "Steam isn't responding right now. Try again in a minute."
    case 503:
      return "The database isn't available. Make sure it's running (docker compose up -d)."
    default:
      return `Something went wrong on the server (HTTP ${status}).`
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error // request was cancelled on purpose
    throw new ApiError(null, `Can't reach the API at ${API_URL}. Is it running? Start it with docker compose up -d.`)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, messageFor(response.status, body?.detail))
  }
  return response.json() as Promise<T>
}

export function searchGames(query: string, signal?: AbortSignal) {
  return request<SearchResponse>(`/search?${new URLSearchParams({ q: query })}`, { signal })
}

export function getSummary(appId: number, signal?: AbortSignal) {
  return request<Summary>(`/games/${appId}/summary`, { signal })
}

export function getTrend(appId: number, signal?: AbortSignal) {
  return request<Trend>(`/games/${appId}/trend`, { signal })
}

export function getReviews(appId: number, sentiment: Sentiment | null, page: number, pageSize: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (sentiment) params.set('sentiment', sentiment)
  return request<ReviewPage>(`/games/${appId}/reviews?${params}`, { signal })
}

export function fetchFromSteam(appId: number, maxReviews: number) {
  return request<FetchResult>(`/games/${appId}/fetch?max_reviews=${maxReviews}`, { method: 'POST' })
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

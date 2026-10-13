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

export interface StoredGame {
  app_id: number
  name: string | null // null until Steam's store details could be looked up
  image_url: string // Steam's wide header image
  total_reviews: number
  negative_pct: number
  neutral_pct: number
  positive_pct: number
}

export interface StoredGames {
  total_reviews: number // across every stored game
  games: StoredGame[] // most reviews first
}

export interface TrendMonth {
  month: string // its first day, "2026-09-01"
  avg_compound: number // -1 to +1: the average of the month's weekly averages, so each week counts once
  review_count: number
  weeks: number // weeks in the month that have reviews
}

export interface Trend {
  app_id: number
  months: TrendMonth[] // only months with reviews; there can be gaps
  weeks_to_fill: number // weeks of the past year under 30 reviews that fillTrendGaps hasn't asked Steam about yet
}

export interface GapFillResult {
  app_id: number
  filled_weeks: number // weeks this request asked Steam about
  new_reviews: number
  remaining: number // weeks still to fill; call again for the next ones
}

export interface WindowStats {
  reviews: number
  avg_score: number | null // average model score, -1 to +1
  recommended_pct: number | null // share of these reviewers who voted Recommended
}

export interface UpdatePost {
  gid: string
  title: string
  url: string
  posted_at: string
}

export type UpdateStatus = 'ready' | 'too_few_reviews' | 'needs_reviews' | 'too_recent'

export interface UpdateComparison {
  day: string // "2026-09-22": compared are the 14 days before it and the 14 after
  posts: UpdatePost[] // the update, plus further update posts less than 14 days after it
  status: UpdateStatus
  before: WindowStats | null
  after: WindowStats | null
  shift: number | null // after minus before, in average score
}

export interface Updates {
  app_id: number
  window_days: number
  min_reviews: number // per side, to be ranked
  updates: UpdateComparison[] // last 12 months, newest first
  biggest_rises: UpdateComparison[]
  biggest_drops: UpdateComparison[]
}

export interface UpdateFetchResult {
  app_id: number
  updates_found: number
  fetched_day: string | null
  new_reviews: number
  remaining: number
}

export type Topic = 'performance' | 'bugs' | 'price' | 'story' | 'gameplay' | 'graphics' | 'multiplayer' | 'content'

export interface TopicExample {
  recommendation_id: number
  excerpt: string // the part of the review that mentions the topic
  sentiment_score: number // the model's score for the excerpt alone, -1 to +1
  voted_up: boolean
  helpful_votes: number
}

export interface TopicSummary {
  topic: Topic
  mentions: number // reviews that mention the topic
  positive: number // of those: praise / model unsure / complaints
  neutral: number
  negative: number
  praise: TopicExample[] // up to 3, most helpful first
  complaints: TopicExample[]
}

export interface Topics {
  app_id: number
  total_reviews: number // every scored review, including those that mention no topic
  topics: TopicSummary[] // every topic, most mentioned first
}

export type PlaytimeGroup = 'under_2h' | '2_to_10h' | '10_to_50h' | '50h_plus'

export interface PlaytimeGroupStats {
  group: PlaytimeGroup
  reviews: number
  recommended: number // how many of them voted Recommended
  recommended_pct: number | null // null when the group has fewer than min_reviews: too few to compare
  avg_score: number | null // average model score, -1 to +1; null likewise
}

export interface Playtime {
  app_id: number
  total_reviews: number
  min_reviews: number // a group needs this many for its percentages
  unknown_playtime: number // reviews Steam sent without a playtime; they're in no group
  groups: PlaytimeGroupStats[] // always all four, shortest playtime first
}

export interface OfftopicPeriod {
  start: string
  end: string // for a period still going on, when Steam was asked
  reviews_left_out: number // English reviews posted in the period that Steam leaves out by default
  negative_left_out: number // how many of those are Not recommended
  still_flagged: boolean // the period was still going on when Steam was asked
}

export interface Offtopic {
  app_id: number
  checked_at: string // answers are cached for an hour
  periods: OfftopicPeriod[] // oldest first; empty if Valve never flagged the game
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
    case 429:
      return 'Steam is limiting requests right now. Try again in a minute.'
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

/** Every stored game with its sentiment split, for the front page. */
export function getGames(signal?: AbortSignal) {
  return request<StoredGames>('/games', { signal })
}

/** A game's name and cover, for a dashboard opened from its web address. 404: Steam has no page for it. */
export function getDetails(appId: number, signal?: AbortSignal) {
  return request<SearchResult>(`/games/${appId}/details`, { signal })
}

export function getTrend(appId: number, signal?: AbortSignal) {
  return request<Trend>(`/games/${appId}/trend`, { signal })
}

/** Fetches the newest 100 reviews of up to 10 past weeks with fewer than 30 stored (about 15 seconds). */
export function fillTrendGaps(appId: number, signal?: AbortSignal) {
  return request<GapFillResult>(`/games/${appId}/trend/fill`, { method: 'POST', signal })
}

export function getTopics(appId: number, signal?: AbortSignal) {
  return request<Topics>(`/games/${appId}/topics`, { signal })
}

export function getPlaytime(appId: number, signal?: AbortSignal) {
  return request<Playtime>(`/games/${appId}/playtime`, { signal })
}

/** Asks Steam (through our API) for periods Valve flagged as off-topic review activity. */
export function getOfftopic(appId: number, signal?: AbortSignal) {
  return request<Offtopic>(`/games/${appId}/offtopic`, { signal })
}

export function getUpdates(appId: number, signal?: AbortSignal) {
  return request<Updates>(`/games/${appId}/updates`, { signal })
}

/** Reads the game's Steam news, then fetches the reviews around one update (about 35 seconds). */
export function fetchUpdateReviews(appId: number, signal?: AbortSignal) {
  return request<UpdateFetchResult>(`/games/${appId}/updates/fetch`, { method: 'POST', signal })
}

export function getReviews(
  appId: number, sentiment: Sentiment | null, playtime: PlaytimeGroup | null, page: number, pageSize: number,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (sentiment) params.set('sentiment', sentiment)
  if (playtime) params.set('playtime', playtime)
  return request<ReviewPage>(`/games/${appId}/reviews?${params}`, { signal })
}

export function fetchFromSteam(appId: number, maxReviews: number) {
  return request<FetchResult>(`/games/${appId}/fetch?max_reviews=${maxReviews}`, { method: 'POST' })
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

/** Resolves after `ms`, or rejects like a cancelled request if `signal` aborts first. */
export function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })
}

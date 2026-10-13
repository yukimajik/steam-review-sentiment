// The page's web address. "/" is the front page; "/game/570/dota-2" is a game's dashboard. Only the
// number is read: the name is there for people reading the link, so an old or missing name still works.

const GAME_PATH = /^\/game\/(\d{1,10})(?:\/[^/]*)?\/?$/
const MAX_APP_ID = 2 ** 31 - 1 // the API's limit (the database column is an INTEGER)

/** The app ID in an address, or null for the front page and for addresses that aren't a game. */
export function appIdFromPath(path: string): number | null {
  const match = GAME_PATH.exec(path)
  if (!match) return null
  const appId = Number(match[1])
  return appId > 0 && appId <= MAX_APP_ID ? appId : null
}

/** "/game/570/dota-2". Names with no letters or digits we can put in an address leave the name out. */
export function gamePath(appId: number, name?: string): string {
  const slug = name ? slugify(name) : ''
  return slug ? `/game/${appId}/${slug}` : `/game/${appId}`
}

// "Baldur's Gate 3" → "baldurs-gate-3", "Pokémon" → "pokemon"
function slugify(name: string): string {
  return name
    .replace(/[™®©]/g, '') // before NFKD, which would turn ™ into "TM"
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '') // accents split off by NFKD
    .toLowerCase()
    .replace(/['’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

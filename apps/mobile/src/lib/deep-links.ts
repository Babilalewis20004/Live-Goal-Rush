/** Where a notification tap (or a link opened from outside the app) should go.
 *
 * Push payloads carry `{type, id}` (the contract the backend's
 * `NotificationService` and the web service worker share). For an article `id`
 * is its slug. Only the screens below can ever be opened this way, and the id
 * must look like an id/slug, so a malformed or hostile payload or URL can't
 * steer the app to an arbitrary route. */
export const DEEP_LINK_TYPES = ["match", "team", "competition", "player", "article", "poll", "editor"] as const
export type DeepLinkType = (typeof DEEP_LINK_TYPES)[number]

const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$/

// The public website also answers on plural paths (/matches/12, /teams/3, ...).
const ALIASES: Record<string, DeepLinkType> = {
  match: "match",
  matches: "match",
  team: "team",
  teams: "team",
  competition: "competition",
  competitions: "competition",
  player: "player",
  players: "player",
  article: "article",
  poll: "poll",
  editor: "editor",
}

export function hrefForNotification(data: { type?: unknown; id?: unknown } | null | undefined): string | null {
  if (!data || typeof data.type !== "string") return null
  if (data.type === "premium") return "/premium" // subscription notices: one screen, no id
  if (!(DEEP_LINK_TYPES as readonly string[]).includes(data.type)) return null
  if (typeof data.id !== "string" && typeof data.id !== "number") return null
  const id = String(data.id)
  return ID.test(id) ? `/${data.type}/${id}` : null
}

/** `https://site/article/some-slug`, `/matches/12?x=1`, `mobile://teams/3` ->
 * the app's own path, or null when it is not one of the supported screens. */
export function hrefForUrl(url: string): string | null {
  let rest = url.trim()
  const scheme = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]*)(.*)$/i.exec(rest)
  if (scheme) {
    const [, authority, tail] = scheme
    // Custom-scheme links put the route first (`mobile://teams/3`); web URLs put a host first.
    rest = authority.toLowerCase() in ALIASES ? `/${authority}${tail}` : tail
  }
  const parts = rest.split(/[?#]/)[0].split("/").filter(Boolean)
  if (parts.length < 2) return null
  const type = ALIASES[parts[0].toLowerCase()]
  if (!type) return null
  let id: string
  try {
    id = decodeURIComponent(parts[1])
  } catch {
    return null
  }
  return hrefForNotification({ type, id })
}

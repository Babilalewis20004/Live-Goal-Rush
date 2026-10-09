/** The public web origin, for share links. Set `EXPO_PUBLIC_SITE_URL` to the real
 * site; the default only suits local development. Shared links are always the
 * canonical public URL of the thing -- never anything about the sharer. */
export const SITE_URL = (process.env.EXPO_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "")

export type ShareableKind = "article" | "match" | "team" | "player" | "competition"

export function publicUrl(kind: ShareableKind, id: number | string): string {
  return `${SITE_URL}/${kind}/${encodeURIComponent(String(id))}`
}

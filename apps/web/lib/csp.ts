/** Content-Security-Policy for every page response (Phase 7).
 *
 * Built per request in `proxy.ts` with a fresh nonce, so only scripts Next.js itself emits
 * (plus the scripts they load, via 'strict-dynamic') can run -- an injected `<script>` or an
 * inline event handler is refused. Every page here is rendered on demand, which nonces need.
 *
 * What the app legitimately talks to:
 *   - the API, for client-side calls (search suggestions, tracking, login, the editor)
 *   - the same API's WebSocket, for live scores
 *   - images from the API (uploaded media) and from article hosts, so any https image
 *   - the billing provider's hosted checkout, reached by a top-level redirect (not governed by CSP)
 */

function origin(value: string | undefined): string | null {
  if (!value) return null
  try {
    return new URL(value).origin
  } catch {
    return null
  }
}

/** `ws://host` / `wss://host` for an http(s) API origin when no explicit WS URL is configured. */
function websocketOrigin(apiOrigin: string | null, wsUrl: string | undefined): string | null {
  const explicit = origin(wsUrl?.replace(/^ws/, "http"))
  if (explicit) return explicit.replace(/^http/, "ws")
  return apiOrigin ? apiOrigin.replace(/^http/, "ws") : null
}

export interface CspOptions {
  nonce: string
  isDev?: boolean
  apiUrl?: string
  wsUrl?: string
  /** The canonical site origin. `upgrade-insecure-requests` is only sent for an https site: on plain-http
   * local Docker it would rewrite the API calls to https and break them. */
  siteUrl?: string
}

export function buildCsp({ nonce, isDev = false, apiUrl, wsUrl, siteUrl }: CspOptions): string {
  const apiOrigin = origin(apiUrl)
  const wsOrigin = websocketOrigin(apiOrigin, wsUrl)
  const connect = ["'self'", apiOrigin, wsOrigin].filter(Boolean).join(" ")
  const directives = [
    "default-src 'self'",
    // 'unsafe-eval' only in development: React uses eval for debugging stacks there.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // Style elements need the nonce; style="" attributes (component libraries set them) are allowed
    // separately -- an attribute cannot run script.
    `style-src 'self' 'nonce-${nonce}'`,
    "style-src-attr 'unsafe-inline'",
    `img-src 'self' data: blob: https:${apiOrigin ? ` ${apiOrigin}` : ""}`,
    "font-src 'self' data:",
    `connect-src ${connect}`,
    "media-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ]
  if (!isDev && siteUrl?.startsWith("https://")) directives.push("upgrade-insecure-requests")
  return directives.join("; ")
}

export function generateNonce(): string {
  return btoa(crypto.randomUUID())
}

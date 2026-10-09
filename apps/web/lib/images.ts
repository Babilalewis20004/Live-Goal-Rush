/** Which images go through Next's optimizer (resized + WebP + cached) and which are served as they are.
 *
 * Crests from the football provider's CDN are large originals shown tiny, so they are optimised. Anything else -- a crest
 * from an unknown host, an SVG (already tiny, and the optimizer refuses SVG), an article image from an arbitrary
 * https host, our own pre-optimised media -- is `unoptimized`. The allow-list must match `images.remotePatterns` in
 * next.config.mjs: `next/image` throws while rendering if it is asked to optimise a host that is not configured. */

const DEFAULT_HOSTS = "media.api-sports.io,crests.football-data.org"

export function crestImageHosts(): string[] {
  return (process.env.NEXT_PUBLIC_CREST_IMAGE_HOSTS ?? DEFAULT_HOSTS)
    .split(",")
    .map((host) => host.trim().toLowerCase())
    .filter(Boolean)
}

/** True when `src` is an https crest on an allowed host and is not an SVG. */
export function shouldOptimizeCrest(src: string | null | undefined): boolean {
  if (!src) return false
  try {
    const url = new URL(src)
    if (url.protocol !== "https:") return false
    if (url.pathname.toLowerCase().endsWith(".svg")) return false
    return crestImageHosts().includes(url.hostname.toLowerCase())
  } catch {
    return false
  }
}

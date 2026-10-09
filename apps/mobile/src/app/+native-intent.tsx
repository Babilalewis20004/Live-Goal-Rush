import { hrefForUrl } from "@/lib/deep-links"

/** Rewrites incoming links before routing: the public site's plural paths
 * (`/matches/12`, `/teams/3`) open the app's own screens, and only the
 * supported screens can be opened from outside. Anything else is left to the
 * router's default handling. */
export function redirectSystemPath({ path }: { path: string; initial: boolean }): string | null {
  try {
    return hrefForUrl(path)
  } catch {
    return null
  }
}

import type { MetadataRoute } from "next"

import { SITE_URL } from "@/lib/seo"

// Read the site URL at request time, not baked into the build.
export const dynamic = "force-dynamic"

/** Public football pages are crawlable. Account, personalised and tooling
 * pages are not (they are also auth-gated, and `noindex`ed where they render),
 * and search result pages are infinite duplicate content. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/profile", "/favourites", "/settings", "/editor", "/u", "/login", "/register", "/forgot-password", "/reset-password", "/search"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  }
}

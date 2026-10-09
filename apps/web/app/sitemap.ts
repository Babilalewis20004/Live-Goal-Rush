import type { MetadataRoute } from "next"

import { api } from "@/lib/api"
import { absoluteUrl } from "@/lib/seo"

export const dynamic = "force-dynamic"

const PAGE = 100
const MAX_ARTICLES = 5000 // sitemap files are capped at 50k URLs; stay well inside

/** Home, news, competitions and every published article. Teams, players and
 * matches are reached through internal links (competition tables, article
 * entity chips, search); they are not listed individually because there is no
 * bulk listing endpoint for them. The API being down degrades to the static
 * entries rather than failing the sitemap. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    { url: absoluteUrl("/"), changeFrequency: "hourly", priority: 1 },
    { url: absoluteUrl("/news"), changeFrequency: "hourly", priority: 0.8 },
    { url: absoluteUrl("/competitions"), changeFrequency: "daily", priority: 0.7 },
  ]

  try {
    const competitions = await api.getCompetitions(1, 100)
    for (const c of competitions.items) {
      entries.push({ url: absoluteUrl(`/competition/${c.id}`), changeFrequency: "daily", priority: 0.7 })
    }
  } catch {
    // keep going with what we have
  }

  try {
    for (let page = 1; entries.length < MAX_ARTICLES; page++) {
      const batch = await api.getArticles({ page, pageSize: PAGE })
      for (const a of batch.items) {
        entries.push({
          url: absoluteUrl(`/article/${a.slug}`),
          lastModified: a.published_at ?? undefined,
          changeFrequency: "weekly",
          priority: 0.6,
        })
      }
      if (page * PAGE >= batch.total || batch.items.length === 0) break
    }
  } catch {
    // keep going with what we have
  }

  return entries
}

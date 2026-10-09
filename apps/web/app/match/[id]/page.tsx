import type { Metadata } from "next"
import { notFound } from "next/navigation"
import { cache } from "react"
import { AnimatedBackground } from "@/components/animated-background"
import { MatchDetailLive } from "@/components/match-detail-live"
import { TrackView } from "@/components/news/track-view"
import { api, ApiError } from "@/lib/api"
import { absoluteUrl, jsonLdScript, matchJsonLd, matchMetadata } from "@/lib/seo"
import { getServerFavourites } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

/** The supplementary match-centre resources are each allowed to fail on their
 * own (the tab shows an honest empty state) -- only the match itself is
 * essential to render the page. */
async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

const loadMatch = cache(async (matchId: number) => {
  try {
    return await api.getMatch(matchId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
})

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const matchId = Number((await params).id)
  const match = Number.isInteger(matchId) ? await loadMatch(matchId) : null
  if (!match) return { title: "Match not found", robots: { index: false, follow: false } }
  return matchMetadata(match)
}

export default async function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const matchId = Number(id)
  if (!Number.isInteger(matchId)) notFound()

  const match = await loadMatch(matchId)
  if (!match) notFound()

  const [capabilities, lineups, statistics, form, headToHead, standings, favourites, news, insights] = await Promise.all([
    optional(api.getCapabilities()),
    optional(api.getMatchLineups(matchId)),
    optional(api.getMatchStatistics(matchId)),
    optional(api.getMatchForm(matchId)),
    optional(api.getMatchHeadToHead(matchId)),
    optional(api.getStandings(match.competition.id)),
    getServerFavourites(),
    optional(api.getMatchNews(matchId)),
    optional(api.getMatchInsights(matchId)),
  ])
  const initialFollowed = favourites?.matches.some((f) => f.match.id === matchId) ?? false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(matchJsonLd(match)) }} />
      <TrackView entity="match" id={matchId} />
      <MatchDetailLive
        initialMatch={match}
        initialFollowed={initialFollowed}
        data={{ capabilities, lineups, statistics, form, headToHead, standings, news, insights, shareUrl: absoluteUrl(`/match/${matchId}`) }}
      />
    </main>
  )
}

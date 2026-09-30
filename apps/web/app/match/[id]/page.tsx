import { notFound } from "next/navigation"
import { AnimatedBackground } from "@/components/animated-background"
import { MatchDetailLive } from "@/components/match-detail-live"
import { api, ApiError } from "@/lib/api"
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

export default async function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const matchId = Number(id)
  if (!Number.isInteger(matchId)) notFound()

  let match
  try {
    match = await api.getMatch(matchId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound()
    throw error
  }

  const [capabilities, lineups, statistics, form, headToHead, standings, favourites] = await Promise.all([
    optional(api.getCapabilities()),
    optional(api.getMatchLineups(matchId)),
    optional(api.getMatchStatistics(matchId)),
    optional(api.getMatchForm(matchId)),
    optional(api.getMatchHeadToHead(matchId)),
    optional(api.getStandings(match.competition.id)),
    getServerFavourites(),
  ])
  const initialFollowed = favourites?.matches.some((f) => f.match.id === matchId) ?? false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <MatchDetailLive
        initialMatch={match}
        initialFollowed={initialFollowed}
        data={{ capabilities, lineups, statistics, form, headToHead, standings }}
      />
    </main>
  )
}

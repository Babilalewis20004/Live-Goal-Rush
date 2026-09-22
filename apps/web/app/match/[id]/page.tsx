import { notFound } from "next/navigation"
import { AnimatedBackground } from "@/components/animated-background"
import { MatchDetailLive } from "@/components/match-detail-live"
import { api, ApiError } from "@/lib/api"
import { getServerFavourites } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

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

  const favourites = await getServerFavourites()
  const initialFollowed = favourites?.matches.some((f) => f.match.id === matchId) ?? false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <MatchDetailLive initialMatch={match} initialFollowed={initialFollowed} />
    </main>
  )
}

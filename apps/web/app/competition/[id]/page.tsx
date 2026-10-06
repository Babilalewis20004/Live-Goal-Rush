import { notFound } from "next/navigation"
import Link from "next/link"
import { AnimatedBackground } from "@/components/animated-background"
import { CompetitionCentre } from "@/components/competition-centre"
import { CompetitionHeader } from "@/components/competition-header"
import { api, ApiError } from "@/lib/api"
import { getServerFavourites } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

export default async function CompetitionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const competitionId = Number(id)
  if (!Number.isInteger(competitionId)) notFound()

  let competition
  try {
    competition = await api.getCompetition(competitionId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound()
    throw error
  }

  const [fixtures, results, standings, topScorers, capabilities, seasons, favourites] = await Promise.all([
    api.getCompetitionFixtures(competitionId, 1, 50, "upcoming"),
    api.getCompetitionFixtures(competitionId, 1, 50, "results"),
    optional(api.getStandings(competitionId)),
    optional(api.getTopScorers(competitionId)),
    optional(api.getCapabilities()),
    optional(api.getCompetitionSeasons(competitionId)),
    getServerFavourites(),
  ])
  const initialFollowed = favourites?.competitions.some((f) => f.competition.id === competitionId) ?? false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>

        <div className="mt-4">
          <CompetitionHeader competition={competition} initialFollowed={initialFollowed} />
        </div>

        <div className="mt-4">
          <CompetitionCentre
            data={{
              competitionId,
              seasons,
              standings,
              fixtures: fixtures.items,
              results: results.items,
              topScorers,
              capabilities,
            }}
          />
        </div>
      </div>
    </main>
  )
}

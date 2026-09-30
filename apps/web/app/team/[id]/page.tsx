import { notFound } from "next/navigation"
import Link from "next/link"
import { AnimatedBackground } from "@/components/animated-background"
import { TeamCentre } from "@/components/team-centre"
import { TeamHeader } from "@/components/team-header"
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

export default async function TeamPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const teamId = Number(id)
  if (!Number.isInteger(teamId)) notFound()

  let team
  try {
    team = await api.getTeam(teamId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound()
    throw error
  }

  const [fixtures, results, favourites, capabilities, overall, home, away, squad, statistics] = await Promise.all([
    api.getTeamFixtures(teamId),
    api.getTeamResults(teamId, 1, 20),
    getServerFavourites(),
    optional(api.getCapabilities()),
    optional(api.getTeamForm(teamId, "overall")),
    optional(api.getTeamForm(teamId, "home")),
    optional(api.getTeamForm(teamId, "away")),
    optional(api.getTeamSquad(teamId)),
    optional(api.getTeamStatistics(teamId)),
  ])
  const initialFollowed = favourites?.teams.some((f) => f.team.id === teamId) ?? false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>

        <div className="mt-4">
          <TeamHeader team={team} initialFollowed={initialFollowed} />
        </div>

        <div className="mt-4">
          <TeamCentre
            data={{
              team,
              fixtures: fixtures.items,
              results: results.items,
              form: { overall, home, away },
              squad,
              statistics,
              capabilities,
            }}
          />
        </div>
      </div>
    </main>
  )
}

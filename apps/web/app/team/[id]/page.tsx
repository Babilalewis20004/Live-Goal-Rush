import { notFound } from "next/navigation"
import Link from "next/link"
import { AnimatedBackground } from "@/components/animated-background"
import { TeamHeader } from "@/components/team-header"
import { MatchCard } from "@/components/match-card"
import { EmptyState } from "@/components/ui/empty-state"
import { api, ApiError } from "@/lib/api"

export const dynamic = "force-dynamic"

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

  const [fixtures, results] = await Promise.all([
    api.getTeamFixtures(teamId),
    api.getTeamResults(teamId),
  ])

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>

        <div className="mt-4">
          <TeamHeader team={team} />
        </div>

        <section className="mt-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
          <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">
            Upcoming Fixtures
          </h2>
          {fixtures.items.length === 0 ? (
            <div className="px-4 py-4">
              <EmptyState message="No upcoming fixtures." />
            </div>
          ) : (
            <div className="divide-y divide-white/[0.06]">
              {fixtures.items.map((match) => (
                <MatchCard key={match.id} match={match} />
              ))}
            </div>
          )}
        </section>

        <section className="mt-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
          <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">
            Recent Results
          </h2>
          {results.items.length === 0 ? (
            <div className="px-4 py-4">
              <EmptyState message="No recent results." />
            </div>
          ) : (
            <div className="divide-y divide-white/[0.06]">
              {results.items.map((match) => (
                <MatchCard key={match.id} match={match} />
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

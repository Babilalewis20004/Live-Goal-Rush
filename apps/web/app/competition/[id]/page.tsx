import { notFound } from "next/navigation"
import Link from "next/link"
import { AnimatedBackground } from "@/components/animated-background"
import { CompetitionHeader } from "@/components/competition-header"
import { MatchCard } from "@/components/match-card"
import { TeamBadge } from "@/components/team-badge"
import { EmptyState } from "@/components/ui/empty-state"
import { api, ApiError } from "@/lib/api"

export const dynamic = "force-dynamic"

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

  const [fixtures, standings] = await Promise.all([
    api.getCompetitionFixtures(competitionId),
    api.getStandings(competitionId),
  ])

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>

        <div className="mt-4">
          <CompetitionHeader competition={competition} />
        </div>

        <section className="mt-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
          <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">Fixtures</h2>
          {fixtures.items.length === 0 ? (
            <div className="px-4 py-4">
              <EmptyState message="No fixtures available." />
            </div>
          ) : (
            <div className="divide-y divide-white/[0.06]">
              {fixtures.items.map((match) => (
                <MatchCard key={match.id} match={match} />
              ))}
            </div>
          )}
        </section>

        {standings.length > 0 && (
          <section className="mt-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
            <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">Standings</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-white/40">
                  <th className="w-8 py-2 pl-4 text-left font-medium">#</th>
                  <th className="py-2 text-left font-medium">Team</th>
                  <th className="w-8 py-2 text-center font-medium">P</th>
                  <th className="w-8 py-2 text-center font-medium">W</th>
                  <th className="w-8 py-2 text-center font-medium">D</th>
                  <th className="w-8 py-2 text-center font-medium">L</th>
                  <th className="w-10 py-2 text-center font-medium">GD</th>
                  <th className="w-10 py-2 pr-4 text-center font-medium">Pts</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {standings.map((row) => (
                  <tr key={row.team.id}>
                    <td className="py-2 pl-4 text-white/60">{row.position}</td>
                    <td className="py-2">
                      <Link href={`/team/${row.team.id}`} className="flex items-center gap-2 hover:underline">
                        <TeamBadge name={row.team.name} shortName={row.team.short_name} logoUrl={row.team.logo_url} size={20} />
                        <span className="truncate text-white/90">{row.team.name}</span>
                      </Link>
                    </td>
                    <td className="py-2 text-center text-white/60">{row.played}</td>
                    <td className="py-2 text-center text-white/60">{row.won}</td>
                    <td className="py-2 text-center text-white/60">{row.drawn}</td>
                    <td className="py-2 text-center text-white/60">{row.lost}</td>
                    <td className="py-2 text-center text-white/60">{row.goals_for - row.goals_against}</td>
                    <td className="py-2 pr-4 text-center font-semibold text-white">{row.points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
    </main>
  )
}

import { Suspense } from "react"
import Link from "next/link"
import { AnimatedBackground } from "@/components/animated-background"
import { CompetitionCard } from "@/components/competition-card"
import { SearchBar } from "@/components/search-bar"
import { TeamBadge } from "@/components/team-badge"
import { MatchCard } from "@/components/match-card"
import { EmptyState } from "@/components/ui/empty-state"
import { api } from "@/lib/api"

export const dynamic = "force-dynamic"

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>
}) {
  const { q = "" } = await searchParams
  const hasQuery = q.trim().length > 0
  const results = hasQuery ? await api.search(q) : null
  const hasResults =
    results !== null &&
    (results.teams.length > 0 ||
      results.competitions.length > 0 ||
      results.players.length > 0 ||
      results.matches.length > 0)

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>

        <h1 className="mb-4 mt-4 text-lg font-bold text-white">Search</h1>

        <Suspense fallback={<div className="h-11 rounded-xl border border-white/10 bg-white/[0.03]" />}>
          <SearchBar />
        </Suspense>

        <div className="mt-4 space-y-6">
          {!hasQuery && <EmptyState message="Search for teams, players, competitions or matches." />}
          {hasQuery && !hasResults && <EmptyState message={`No results for "${q}".`} />}

          {results && results.teams.length > 0 && (
            <section>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">Teams</h2>
              <div className="space-y-2">
                {results.teams.map((team) => (
                  <Link
                    key={team.id}
                    href={`/team/${team.id}`}
                    className="flex items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06]"
                  >
                    <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} />
                    <span className="text-sm text-white">{team.name}</span>
                  </Link>
                ))}
              </div>
            </section>
          )}

          {results && results.competitions.length > 0 && (
            <section>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">Competitions</h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {results.competitions.map((competition) => (
                  <CompetitionCard key={competition.id} competition={competition} />
                ))}
              </div>
            </section>
          )}

          {results && results.players.length > 0 && (
            <section>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">Players</h2>
              <div className="space-y-2">
                {results.players.map((player) => (
                  <Link
                    key={player.id}
                    href={`/player/${player.id}`}
                    className="flex items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06]"
                  >
                    <span className="text-sm text-white">{player.name}</span>
                    {player.position && <span className="text-xs text-white/40">{player.position}</span>}
                  </Link>
                ))}
              </div>
            </section>
          )}

          {results && results.matches.length > 0 && (
            <section>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">Matches</h2>
              <div className="divide-y divide-white/[0.06] overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.03]">
                {results.matches.map((match) => (
                  <MatchCard key={match.id} match={match} />
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </main>
  )
}

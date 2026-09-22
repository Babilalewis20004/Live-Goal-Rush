import Link from "next/link"

import { LeagueLogo } from "@/components/league-logo"
import { MatchCard } from "@/components/match-card"
import { TeamBadge } from "@/components/team-badge"
import { getServerFavourites, getServerUser } from "@/lib/server-auth"
import type { MatchSummary } from "@/types/api"

/** Additive personalisation layered above the existing public board
 * (Phase 3 §11) -- renders nothing at all for an anonymous visitor, who
 * sees exactly the same page Phase 2 shipped. `liveMatches` is passed in
 * from the page's own already-fetched data rather than re-queried here. */
export async function PersonalizedHome({ liveMatches }: { liveMatches: MatchSummary[] }) {
  const user = await getServerUser()
  if (!user) return null

  const favourites = await getServerFavourites()
  if (!favourites) return null

  const followedTeamIds = new Set(favourites.teams.map((f) => f.team.id))
  const followedCompetitionIds = new Set(favourites.competitions.map((f) => f.competition.id))
  const followedMatchIds = new Set(favourites.matches.map((f) => f.match.id))

  const myLiveMatches = liveMatches.filter(
    (m) =>
      followedMatchIds.has(m.id) ||
      followedTeamIds.has(m.home_team.id) ||
      followedTeamIds.has(m.away_team.id) ||
      followedCompetitionIds.has(m.competition.id),
  )

  const hasAnyFavourites =
    favourites.teams.length > 0 || favourites.competitions.length > 0 || favourites.matches.length > 0

  if (!hasAnyFavourites) return null

  return (
    <section className="mx-auto max-w-2xl px-4 pt-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">Your feed</h2>
        <Link href="/favourites" className="text-xs text-white/40 hover:text-white/70">
          Manage favourites →
        </Link>
      </div>

      {(favourites.teams.length > 0 || favourites.competitions.length > 0) && (
        <div className="mb-4 flex flex-wrap gap-2">
          {favourites.teams.map((f) => (
            <Link
              key={`team-${f.team.id}`}
              href={`/team/${f.team.id}`}
              className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-white/80 hover:bg-white/[0.06]"
            >
              <TeamBadge name={f.team.name} shortName={f.team.short_name} logoUrl={f.team.logo_url} size={16} />
              {f.team.name}
            </Link>
          ))}
          {favourites.competitions.map((f) => (
            <Link
              key={`competition-${f.competition.id}`}
              href={`/competition/${f.competition.id}`}
              className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-white/80 hover:bg-white/[0.06]"
            >
              <LeagueLogo name={f.competition.name} logoUrl={f.competition.logo_url} size={16} />
              {f.competition.name}
            </Link>
          ))}
        </div>
      )}

      {myLiveMatches.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
          <h3 className="border-b border-white/[0.06] px-4 py-3 text-xs font-semibold uppercase tracking-wide text-white/50">
            Live now
          </h3>
          <div className="divide-y divide-white/[0.06]">
            {myLiveMatches.map((match) => (
              <MatchCard key={match.id} match={match} />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

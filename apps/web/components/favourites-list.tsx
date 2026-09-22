"use client"

import Link from "next/link"
import { useState } from "react"

import { LeagueLogo } from "@/components/league-logo"
import { TeamBadge } from "@/components/team-badge"
import { EmptyState } from "@/components/ui/empty-state"
import { api } from "@/lib/api"
import type { FavouritesOut } from "@/types/api"

export function FavouritesList({ initial }: { initial: FavouritesOut }) {
  const [favourites, setFavourites] = useState(initial)

  async function unfollowTeam(teamId: number) {
    setFavourites((prev) => ({ ...prev, teams: prev.teams.filter((f) => f.team.id !== teamId) }))
    await api.unfollowTeam(teamId).catch(() => {})
  }

  async function unfollowCompetition(competitionId: number) {
    setFavourites((prev) => ({
      ...prev,
      competitions: prev.competitions.filter((f) => f.competition.id !== competitionId),
    }))
    await api.unfollowCompetition(competitionId).catch(() => {})
  }

  async function unfollowMatch(matchId: number) {
    setFavourites((prev) => ({ ...prev, matches: prev.matches.filter((f) => f.match.id !== matchId) }))
    await api.unfollowMatch(matchId).catch(() => {})
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
        <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">
          My Teams
        </h2>
        {favourites.teams.length === 0 ? (
          <div className="px-4 py-4">
            <EmptyState message="You're not following any teams yet." />
          </div>
        ) : (
          <div className="divide-y divide-white/[0.06]">
            {favourites.teams.map((f) => (
              <div key={f.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <Link href={`/team/${f.team.id}`} className="flex min-w-0 items-center gap-3">
                  <TeamBadge name={f.team.name} shortName={f.team.short_name} logoUrl={f.team.logo_url} size={28} />
                  <span className="truncate text-sm text-white/90">{f.team.name}</span>
                </Link>
                <button
                  type="button"
                  onClick={() => unfollowTeam(f.team.id)}
                  className="shrink-0 text-xs text-white/40 hover:text-white/70"
                >
                  Unfollow
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
        <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">
          My Competitions
        </h2>
        {favourites.competitions.length === 0 ? (
          <div className="px-4 py-4">
            <EmptyState message="You're not following any competitions yet." />
          </div>
        ) : (
          <div className="divide-y divide-white/[0.06]">
            {favourites.competitions.map((f) => (
              <div key={f.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <Link href={`/competition/${f.competition.id}`} className="flex min-w-0 items-center gap-3">
                  <LeagueLogo name={f.competition.name} logoUrl={f.competition.logo_url} size={28} />
                  <span className="truncate text-sm text-white/90">{f.competition.name}</span>
                </Link>
                <button
                  type="button"
                  onClick={() => unfollowCompetition(f.competition.id)}
                  className="shrink-0 text-xs text-white/40 hover:text-white/70"
                >
                  Unfollow
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
        <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">
          My Matches
        </h2>
        {favourites.matches.length === 0 ? (
          <div className="px-4 py-4">
            <EmptyState message="You're not following any matches yet." />
          </div>
        ) : (
          <div className="divide-y divide-white/[0.06]">
            {favourites.matches.map((f) => (
              <div key={f.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <Link href={`/match/${f.match.id}`} className="min-w-0 truncate text-sm text-white/90">
                  {f.match.home_team.name} vs {f.match.away_team.name}
                </Link>
                <button
                  type="button"
                  onClick={() => unfollowMatch(f.match.id)}
                  className="shrink-0 text-xs text-white/40 hover:text-white/70"
                >
                  Unfollow
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

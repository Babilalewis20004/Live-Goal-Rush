"use client"

import Link from "next/link"
import { MapPin } from "lucide-react"
import { LeagueLogo } from "@/components/league-logo"
import { TeamBadge } from "@/components/team-badge"
import { MatchEvent } from "@/components/match-event"
import { EmptyState } from "@/components/ui/empty-state"
import { LiveIndicator } from "@/components/ui/live-indicator"
import { ConnectionBadge } from "@/components/ui/connection-badge"
import { useMatchDetail } from "@/hooks/use-match-detail"
import { formatKickoff, formatKickoffDate } from "@/lib/format"
import type { MatchDetail as MatchDetailType } from "@/types/api"

function statusLabel(status: string, minute: number | null): string {
  if (status === "live") return `${minute}'`
  if (status === "halftime") return "Half Time"
  if (status === "finished") return "Full Time"
  if (status === "postponed" || status === "cancelled") return status.toUpperCase()
  return "Scheduled"
}

/** Client half of the match detail page (spec §17): the server component
 * (`app/match/[id]/page.tsx`) does the initial REST fetch so the page
 * still renders real data on first load / with JS disabled; this
 * component takes over from there with `useMatchDetail`'s WebSocket feed. */
export function MatchDetailLive({ initialMatch }: { initialMatch: MatchDetailType }) {
  const { match, connectionStatus } = useMatchDetail(initialMatch)
  const isLive = match.status === "live" || match.status === "halftime"

  return (
    <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
      <div className="flex items-center justify-between">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>
        <ConnectionBadge status={connectionStatus} />
      </div>

      <div className="mt-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
        <div className="flex items-center justify-center gap-2 border-b border-white/[0.06] px-4 py-3">
          <Link
            href={`/competition/${match.competition.id}`}
            className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-white/70 hover:text-white"
          >
            <LeagueLogo name={match.competition.name} logoUrl={match.competition.logo_url} size={18} />
            {match.competition.name}
          </Link>
        </div>

        <div className="flex items-center justify-between gap-3 px-6 py-8">
          <Link
            href={`/team/${match.home_team.id}`}
            className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center"
          >
            <TeamBadge
              name={match.home_team.name}
              shortName={match.home_team.short_name}
              logoUrl={match.home_team.logo_url}
              size={56}
            />
            <span className="truncate text-sm font-medium text-white/90">{match.home_team.name}</span>
          </Link>

          <div className="flex shrink-0 flex-col items-center gap-2 px-2">
            <div className="flex items-center gap-3 text-4xl font-bold tabular-nums text-white">
              <span>{match.home_score}</span>
              <span className="text-white/30">-</span>
              <span>{match.away_score}</span>
            </div>
            <span
              className={[
                "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
                isLive ? "bg-emerald-500/15 text-emerald-400" : "text-white/50",
              ].join(" ")}
            >
              {isLive && <LiveIndicator />}
              {statusLabel(match.status, match.minute)}
            </span>
            {(match.half_time_home_score !== null || match.half_time_away_score !== null) && (
              <span className="text-[11px] text-white/35">
                HT {match.half_time_home_score ?? 0} - {match.half_time_away_score ?? 0}
              </span>
            )}
          </div>

          <Link
            href={`/team/${match.away_team.id}`}
            className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center"
          >
            <TeamBadge
              name={match.away_team.name}
              shortName={match.away_team.short_name}
              logoUrl={match.away_team.logo_url}
              size={56}
            />
            <span className="truncate text-sm font-medium text-white/90">{match.away_team.name}</span>
          </Link>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-white/[0.06] px-4 py-2.5 text-[11px] text-white/40">
          <span>
            {formatKickoffDate(match.kickoff_time)} · {formatKickoff(match.kickoff_time)} UTC
          </span>
          {match.venue && (
            <span className="flex items-center gap-1">
              <MapPin className="h-3 w-3" />
              {match.venue}
            </span>
          )}
        </div>
      </div>

      <section className="mt-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
        <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">Match Events</h2>
        <div className="px-4 py-4">
          {match.events.length === 0 ? (
            <EmptyState message="No events yet." />
          ) : (
            <div className="space-y-2.5">
              {match.events.map((event) => (
                <MatchEvent key={event.id} event={event} isHome={event.team?.id === match.home_team.id} />
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

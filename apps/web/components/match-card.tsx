import Link from "next/link"
import { ChevronRight } from "lucide-react"
import type { MatchSummary } from "@/types/api"
import { formatKickoff } from "@/lib/format"
import { TeamBadge } from "./team-badge"
import { LiveIndicator } from "./ui/live-indicator"
import { ScoreDisplay } from "./ui/score-display"

function StatusPill({ match }: { match: MatchSummary }) {
  if (match.status === "live") {
    return (
      <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-400">
        <LiveIndicator />
        {match.minute}&apos;
      </span>
    )
  }
  if (match.status === "halftime") {
    return (
      <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-400">
        HT
      </span>
    )
  }
  if (match.status === "finished") {
    return <span className="text-[11px] font-semibold text-white/40">FT</span>
  }
  if (match.status === "postponed" || match.status === "cancelled") {
    return <span className="text-[11px] font-semibold text-white/40">{match.status.toUpperCase()}</span>
  }
  return <span className="text-[11px] font-semibold text-white/50">{formatKickoff(match.kickoff_time)}</span>
}

export function MatchCard({ match }: { match: MatchSummary }) {
  const isLive = match.status === "live"
  const scheduled = match.status === "scheduled"
  const homeWin = match.home_score > match.away_score
  const awayWin = match.away_score > match.home_score

  return (
    <Link
      href={`/match/${match.id}`}
      className="group relative flex items-center gap-3 overflow-hidden px-4 py-3 transition-colors hover:bg-white/[0.04]"
    >
      {isLive && (
        <>
          <span className="absolute left-0 top-0 h-full w-0.5 bg-emerald-400" />
          <span className="ls-sweep pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-transparent via-emerald-400/[0.07] to-transparent" />
        </>
      )}

      <div className="w-12 shrink-0 text-center">
        <StatusPill match={match} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <TeamBadge name={match.home_team.name} shortName={match.home_team.short_name} logoUrl={match.home_team.logo_url} />
            <span
              className={[
                "truncate text-sm",
                scheduled ? "text-white/80" : homeWin ? "font-semibold text-white" : "text-white/70",
              ].join(" ")}
            >
              {match.home_team.name}
            </span>
          </div>
          {!scheduled && <ScoreDisplay value={match.home_score} live={isLive} dim={awayWin} />}
        </div>

        <div className="mt-1.5 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <TeamBadge name={match.away_team.name} shortName={match.away_team.short_name} logoUrl={match.away_team.logo_url} />
            <span
              className={[
                "truncate text-sm",
                scheduled ? "text-white/80" : awayWin ? "font-semibold text-white" : "text-white/70",
              ].join(" ")}
            >
              {match.away_team.name}
            </span>
          </div>
          {!scheduled && <ScoreDisplay value={match.away_score} live={isLive} dim={homeWin} />}
        </div>
      </div>

      <ChevronRight className="h-4 w-4 shrink-0 text-white/25 transition-transform group-hover:translate-x-0.5" />
    </Link>
  )
}

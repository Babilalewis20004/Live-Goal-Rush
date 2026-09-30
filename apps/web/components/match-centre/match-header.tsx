import Link from "next/link"
import { MapPin } from "lucide-react"
import { LeagueLogo } from "@/components/league-logo"
import { TeamBadge } from "@/components/team-badge"
import { LiveIndicator } from "@/components/ui/live-indicator"
import { formatKickoff, formatKickoffDate } from "@/lib/format"
import { statusDisplay } from "@/lib/match-centre"
import type { MatchDetail } from "@/types/api"

/** The match-centre header. Everything shown is derived from the app's own
 * normalized status model via `statusDisplay` -- no provider status strings
 * reach the UI. */
export function MatchHeader({ match }: { match: MatchDetail }) {
  const status = statusDisplay(match)
  const summary = status.showScore
    ? `${match.home_team.name} ${match.home_score}, ${match.away_team.name} ${match.away_score}`
    : `${match.home_team.name} versus ${match.away_team.name}`

  return (
    <header
      aria-label={`${summary}. ${status.label}${status.detail ? ` ${status.detail}` : ""}`}
      className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"
    >
      <div className="flex items-center justify-center gap-2 border-b border-white/[0.06] px-4 py-3">
        <Link
          href={`/competition/${match.competition.id}`}
          className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-white/70 hover:text-white"
        >
          <LeagueLogo name={match.competition.name} logoUrl={match.competition.logo_url} size={18} />
          {match.competition.name}
        </Link>
      </div>

      <div className="flex items-center justify-between gap-3 px-4 py-8 sm:px-6">
        <TeamLink team={match.home_team} />

        <div className="flex shrink-0 flex-col items-center gap-2 px-2" aria-hidden="true">
          {status.showScore ? (
            <div className="flex items-center gap-3 text-4xl font-bold tabular-nums text-white">
              <span>{match.home_score}</span>
              <span className="text-white/30">–</span>
              <span>{match.away_score}</span>
            </div>
          ) : (
            <div className="text-3xl font-bold tabular-nums text-white">
              {status.kind === "upcoming" ? status.label : "–"}
            </div>
          )}

          {status.kind === "upcoming" ? (
            <span className="text-[11px] font-semibold text-white/55">{status.detail}</span>
          ) : (
            <span
              className={[
                "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide",
                status.isLive
                  ? "bg-emerald-500/15 text-emerald-400"
                  : status.kind === "postponed" || status.kind === "cancelled"
                    ? "bg-amber-500/15 text-amber-400"
                    : "text-white/55",
              ].join(" ")}
            >
              {status.kind === "live" && <LiveIndicator />}
              {status.label}
            </span>
          )}
          {status.kind === "live" && status.detail && (
            <span className="text-sm font-semibold tabular-nums text-emerald-400">{status.detail}</span>
          )}
          {(match.half_time_home_score !== null || match.half_time_away_score !== null) &&
            status.showScore &&
            status.kind !== "halftime" && (
              <span className="text-[11px] text-white/45">
                HT {match.half_time_home_score ?? 0} – {match.half_time_away_score ?? 0}
              </span>
            )}
        </div>

        <TeamLink team={match.away_team} />
      </div>

      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-white/[0.06] px-4 py-2.5 text-[11px] text-white/50">
        <span>
          {formatKickoffDate(match.kickoff_time)} · {formatKickoff(match.kickoff_time)} UTC
        </span>
        {match.venue && (
          <span className="flex items-center gap-1">
            <MapPin className="h-3 w-3" aria-hidden="true" />
            {match.venue}
          </span>
        )}
      </div>
    </header>
  )
}

function TeamLink({ team }: { team: MatchDetail["home_team"] }) {
  return (
    <Link href={`/team/${team.id}`} className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center">
      <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} size={56} />
      <span className="max-w-full truncate text-sm font-medium text-white/90">{team.name}</span>
    </Link>
  )
}

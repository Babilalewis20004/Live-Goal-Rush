import { formatStat, statRows, type StatRow } from "@/lib/match-centre"
import type { MatchDetail, MatchStatisticsOut } from "@/types/api"

function Row({ row, homeName, awayName }: { row: StatRow; homeName: string; awayName: string }) {
  const home = formatStat(row.home, row.format)
  const away = formatStat(row.away, row.format)
  return (
    <li className="py-2.5">
      <div className="flex items-baseline justify-between text-sm">
        <span className="w-14 font-semibold tabular-nums text-white">{home}</span>
        <span className="text-xs text-white/55">{row.label}</span>
        <span className="w-14 text-right font-semibold tabular-nums text-white">{away}</span>
      </div>
      {/* A comparison bar: the visual duplicates the numbers above, so it is
          exposed to assistive tech as one labelled image instead. */}
      <div
        role="img"
        aria-label={`${row.label}: ${homeName} ${home}, ${awayName} ${away}`}
        className="mt-1.5 flex h-1.5 gap-1 overflow-hidden rounded-full"
      >
        <div className="rounded-full bg-emerald-400/80" style={{ width: `${row.homeShare * 100}%` }} />
        <div className="rounded-full bg-sky-400/70" style={{ width: `${(1 - row.homeShare) * 100}%` }} />
      </div>
    </li>
  )
}

/** Match statistics. Only what the provider supplied is listed: a statistic
 * missing for both teams has no row (never a fake 0), and the caller shows an
 * honest unavailable/not-yet state when there are no rows at all. */
export function Statistics({ match, statistics }: { match: MatchDetail; statistics: MatchStatisticsOut | null }) {
  const rows = statRows(statistics)
  return (
    <section
      aria-label="Match statistics"
      className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"
    >
      <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3 text-xs font-semibold text-white/80">
        <span className="truncate">{match.home_team.name}</span>
        <span className="truncate text-right">{match.away_team.name}</span>
      </div>
      <ul className="divide-y divide-white/[0.05] px-4 py-1">
        {rows.map((row) => (
          <Row key={row.key} row={row} homeName={match.home_team.name} awayName={match.away_team.name} />
        ))}
      </ul>
    </section>
  )
}

export function hasStatistics(statistics: MatchStatisticsOut | null): boolean {
  return statRows(statistics).length > 0
}

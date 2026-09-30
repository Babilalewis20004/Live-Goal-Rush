import Link from "next/link"
import { formatKickoffDate } from "@/lib/format"
import type { HeadToHeadOut, MatchDetail } from "@/types/api"

function yearOf(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" })
}

/** Previous meetings, with the window stated outright ("the last 5 finished
 * meetings since Oct 2016") so the numbers can't be mistaken for an all-time
 * record. History only -- never used to predict anything. */
export function HeadToHead({ match, data }: { match: MatchDetail; data: HeadToHeadOut }) {
  const total = data.meetings.length
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold text-white/80">Head to head</h3>
        <span className="text-[10px] text-white/40">
          {total > 0 ? `Last ${total} meeting${total === 1 ? "" : "s"} since ${yearOf(data.period_start)}` : `Since ${yearOf(data.period_start)}`}
        </span>
      </div>

      {total === 0 ? (
        <p className="text-xs text-white/40">No previous meetings stored for these teams.</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2 text-center" role="group" aria-label="Head to head summary">
            <Count value={data.home_team_wins} label={`${match.home_team.short_name ?? match.home_team.name} wins`} />
            <Count value={data.draws} label="Draws" />
            <Count value={data.away_team_wins} label={`${match.away_team.short_name ?? match.away_team.name} wins`} />
          </div>
          <ul className="mt-3 divide-y divide-white/[0.05]">
            {data.meetings.map((m) => (
              <li key={m.match_id}>
                <Link
                  href={`/match/${m.match_id}`}
                  className="flex items-center gap-2 py-2 text-xs text-white/75 hover:text-white"
                >
                  <span className="w-20 shrink-0 text-[10px] text-white/40">{formatKickoffDate(m.kickoff_time)}</span>
                  <span className="min-w-0 flex-1 truncate">{m.home_team.name}</span>
                  <span className="shrink-0 rounded bg-white/[0.06] px-1.5 py-0.5 font-semibold tabular-nums text-white">
                    {m.home_score} – {m.away_score}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-right">{m.away_team.name}</span>
                </Link>
                <p className="pb-1.5 pl-20 text-[10px] text-white/30">{m.competition.name}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function Count({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-lg bg-white/[0.04] px-2 py-2">
      <div className="text-lg font-bold tabular-nums text-white">{value}</div>
      <div className="truncate text-[10px] text-white/45">{label}</div>
    </div>
  )
}

"use client"

import { LockedNote } from "@/components/analytics/premium-gate"
import { useAsync } from "@/hooks/use-async"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { formatNumber, formatStat } from "@/lib/analytics"
import type { PlayerAnalyticsOut } from "@/types/api"

const CARD = "rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md"

const TOTALS: [string, string][] = [
  ["minutes_played", "Minutes"], ["goals", "Goals"], ["assists", "Assists"], ["shots", "Shots"],
  ["shots_on_target", "On target"], ["key_passes", "Chances created"], ["tackles", "Tackles"], ["interceptions", "Interceptions"],
]
const PER90: [string, string][] = [
  ["goals", "Goals"], ["assists", "Assists"], ["shots", "Shots"], ["key_passes", "Chances created"], ["tackles", "Tackles"],
]

/** A tiny, accessible trend of goal involvements (goals + assists) per match. The numbers are in the
 * table and the aria-label, so the bars are never the only carrier of the information. */
function Trend({ values }: { values: number[] }) {
  const max = Math.max(1, ...values)
  return (
    <div className="flex h-10 items-end gap-1" role="img" aria-label={`Goal involvements in the last ${values.length} matches, oldest to newest: ${values.join(", ")}`}>
      {values.map((v, i) => (
        <div key={i} className="w-4 rounded-sm bg-emerald-400/70" style={{ height: `${Math.max(8, (v / max) * 100)}%` }} title={String(v)} />
      ))}
    </div>
  )
}

export function PlayerAnalyticsView({ data, signedIn, showSeasons = true }: { data: PlayerAnalyticsOut; signedIn: boolean; showSeasons?: boolean }) {
  const full = data.tier === "full"
  return (
    <div className="space-y-4">
      {showSeasons && data.seasons.length > 0 && (
        <section aria-label="Seasons">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">Season history</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-white/70">
              <caption className="sr-only">Appearances, goals and assists by season and competition</caption>
              <thead className="text-white/60">
                <tr><th scope="col" className="py-1 pr-3">Season</th><th scope="col" className="pr-3">Competition</th><th scope="col" className="pr-3 text-right">Apps</th><th scope="col" className="pr-3 text-right">Goals</th><th scope="col" className="text-right">Assists</th></tr>
              </thead>
              <tbody>
                {data.seasons.map((s) => (
                  <tr key={`${s.competition_id}-${s.season}`} className="border-t border-white/[0.05]">
                    <th scope="row" className="py-1 pr-3 font-normal">{s.season}</th>
                    <td className="pr-3">{s.competition_name}</td>
                    <td className="pr-3 text-right tabular-nums">{formatNumber(s.appearances)}</td>
                    <td className="pr-3 text-right tabular-nums">{s.goals}</td>
                    <td className="text-right tabular-nums">{formatNumber(s.assists)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {full && data.matches_with_statistics > 0 && (
        <>
          <section aria-label="Recent totals">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">Last {data.matches_with_statistics} matches with statistics</h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
              {TOTALS.map(([key, label]) => (
                <div key={key}>
                  <dt className="text-[11px] text-white/60">{label}</dt>
                  <dd className="font-semibold tabular-nums text-white">{formatStat(data.totals[key], { digits: 0 })}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section aria-label="Per 90 minutes">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">Per 90 minutes</h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-5">
              {PER90.map(([key, label]) => (
                <div key={key}>
                  <dt className="text-[11px] text-white/60">{label}</dt>
                  <dd className="font-semibold tabular-nums text-white">{formatStat(data.per_90[key], { digits: 2 })}</dd>
                </div>
              ))}
            </dl>
          </section>
          {data.form_goal_involvements.length > 1 && (
            <section aria-label="Form">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">Goals + assists, match by match</h3>
              <Trend values={data.form_goal_involvements} />
            </section>
          )}
          <section aria-label="Match by match">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">Match by match</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-white/70">
                <caption className="sr-only">Statistics in each recent match</caption>
                <thead className="text-white/60">
                  <tr><th scope="col" className="py-1 pr-3">Opponent</th><th scope="col" className="pr-3 text-right">Min</th><th scope="col" className="pr-3 text-right">G</th><th scope="col" className="pr-3 text-right">A</th><th scope="col" className="pr-3 text-right">Shots</th><th scope="col" className="text-right">Chances</th></tr>
                </thead>
                <tbody>
                  {data.recent.map((m) => (
                    <tr key={m.match_id} className="border-t border-white/[0.05]">
                      <th scope="row" className="py-1 pr-3 font-normal">{m.opponent}</th>
                      <td className="pr-3 text-right tabular-nums">{formatNumber(m.minutes)}</td>
                      <td className="pr-3 text-right tabular-nums">{formatNumber(m.goals)}</td>
                      <td className="pr-3 text-right tabular-nums">{formatNumber(m.assists)}</td>
                      <td className="pr-3 text-right tabular-nums">{formatNumber(m.shots)}</td>
                      <td className="text-right tabular-nums">{formatNumber(m.key_passes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <LockedNote locked={data.locked} signedIn={signedIn} />
      {full && data.unavailable.length > 0 && (
        <p className="text-[11px] text-white/60">Not tracked by this platform: {data.unavailable.map((u) => u.replaceAll("_", " ")).join(", ")}.</p>
      )}
      {data.limitations.map((l) => (
        <p key={l} className="text-[11px] text-amber-200/70">{l}</p>
      ))}
    </div>
  )
}

export function PlayerAnalytics({ playerId, showSeasons = true }: { playerId: number; showSeasons?: boolean }) {
  const { user } = useAuth()
  const { data, error, loading } = useAsync(() => api.getPlayerAnalytics(playerId), `player-analytics:${playerId}:${user?.id ?? "anon"}`)
  return (
    <section className={CARD} aria-labelledby="player-analytics-heading">
      <h2 id="player-analytics-heading" className="mb-3 text-sm font-semibold text-white">Performance</h2>
      {loading && !data && <p className="text-xs text-white/60" aria-busy="true">Loading…</p>}
      {error && !data && <p className="text-xs text-white/60">Performance data isn&apos;t available right now.</p>}
      {data && (data.seasons.length > 0 || data.tier === "full" || data.locked.length > 0 ? (
        <PlayerAnalyticsView data={data} signedIn={!!user} showSeasons={showSeasons} />
      ) : (
        <p className="text-xs text-white/60">No performance data has been supplied for this player yet.</p>
      ))}
    </section>
  )
}

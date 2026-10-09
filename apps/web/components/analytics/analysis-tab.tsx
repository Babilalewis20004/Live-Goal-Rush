"use client"

import { useState } from "react"

import { AdSlot } from "@/components/analytics/ad-slot"
import { ComparisonPanel } from "@/components/analytics/comparison-panel"
import { PremiumGate } from "@/components/analytics/premium-gate"
import { PredictionCard } from "@/components/analytics/prediction-card"
import { isPaymentRequired, useAsync } from "@/hooks/use-async"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { formatNumber } from "@/lib/analytics"
import type { MatchDetail } from "@/types/api"

const CARD = "rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md"

/** "Key insights": sentences stored by the insight job, each derived from stored results or
 * live statistics. Live ones (shots, possession) only appear when both teams' numbers exist. */
function KeyInsights({ matchId, nudge }: { matchId: number; nudge: number }) {
  const { data } = useAsync(() => api.getMatchInsightRecords(matchId), `insight-records:${matchId}`, nudge)
  if (!data || data.length === 0) return null
  const live = data.filter((i) => i.insight_type.startsWith("live:"))
  const rest = data.filter((i) => !i.insight_type.startsWith("live:") && !i.insight_type.endsWith("form_summary") && !i.insight_type.endsWith("goal_average"))
  const items = [...live, ...rest].slice(0, 8)
  if (items.length === 0) return null
  return (
    <section className={CARD} aria-labelledby="key-insights-heading">
      <h2 id="key-insights-heading" className="text-sm font-semibold text-white">Key insights</h2>
      <ul className="mt-2 space-y-1.5 text-sm text-white/80">
        {items.map((i) => (
          <li key={i.insight_type} className="flex gap-2">
            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
            <span>
              {i.insight_type.startsWith("live:") && <span className="mr-1 rounded bg-red-500/20 px-1 text-[11px] font-semibold uppercase text-red-200">Live</span>}
              {i.text}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] text-white/60">Each insight is calculated from stored results or live statistics. Historical information, not a prediction.</p>
    </section>
  )
}

const WINDOWS = [
  { id: "last5", label: "Last 5" },
  { id: "last10", label: "Last 10 🔒" },
  { id: "all", label: "All meetings 🔒" },
] as const

function ExtendedHistory({ match }: { match: MatchDetail }) {
  const { user } = useAuth()
  const [window, setWindow] = useState<(typeof WINDOWS)[number]["id"]>("last5")
  const { data, error } = useAsync(
    () => (window === "last5" ? api.getMatchHeadToHead(match.id) : api.getExtendedHeadToHead(match.id, window)),
    `h2h:${match.id}:${window}:${user?.id ?? "anon"}`,
  )
  return (
    <section className={CARD} aria-labelledby="h2h-heading">
      <h2 id="h2h-heading" className="text-sm font-semibold text-white">Head-to-head history</h2>
      <div className="mt-2 flex gap-2" role="group" aria-label="Meetings to include">
        {WINDOWS.map((w) => (
          <button key={w.id} type="button" aria-pressed={window === w.id} onClick={() => setWindow(w.id)}
            className={`rounded-full border px-3 py-1 text-xs ${window === w.id ? "border-emerald-400/60 bg-emerald-400/15 text-white" : "border-white/10 text-white/60 hover:text-white"}`}>
            {w.label}
          </button>
        ))}
      </div>
      {isPaymentRequired(error) ? (
        <div className="mt-3">
          <PremiumGate title="Longer head-to-head history" items={["The last 10 meetings", "Every stored meeting"]} signedIn={!!user} />
        </div>
      ) : data ? (
        <div className="mt-3 text-sm text-white/80">
          <p>
            {data.total_meetings ?? data.meetings.length} meetings: {match.home_team.name} <strong>{data.home_team_wins}</strong> wins, <strong>{data.draws}</strong> draws, {match.away_team.name}{" "}
            <strong>{data.away_team_wins}</strong> wins.
          </p>
          {data.average_goals !== null && data.average_goals !== undefined && (
            <p className="mt-1 text-xs text-white/60">
              {formatNumber(data.average_goals)} goals per meeting ({data.home_team_goals}–{data.away_team_goals} overall).
            </p>
          )}
          {data.recent_form && (
            <p className="mt-1 text-xs text-white/60">
              {match.home_team.name} in these meetings, oldest to newest: <span className="font-mono tracking-widest text-white">{data.recent_form}</span>
            </p>
          )}
          {data.limitation && <p className="mt-1 text-[11px] text-amber-200/70">{data.limitation}</p>}
        </div>
      ) : (
        <p className="mt-3 text-xs text-white/60">{error ? "Head-to-head isn't available right now." : "Loading…"}</p>
      )}
    </section>
  )
}

/** The match centre's Analysis tab: model estimate, comparison, key insights, longer history.
 * Refreshes when the server nudges over the existing match WebSocket. */
export function AnalysisTab({ match, nudges }: { match: MatchDetail; nudges: Record<string, number> }) {
  return (
    <div className="space-y-4">
      <PredictionCard matchId={match.id} homeName={match.home_team.name} awayName={match.away_team.name} nudge={nudges["prediction.updated"] ?? 0} />
      <ComparisonPanel matchId={match.id} />
      <KeyInsights matchId={match.id} nudge={nudges["match.insight.updated"] ?? 0} />
      <ExtendedHistory match={match} />
      <AdSlot placement="match_centre" live={match.status === "live" || match.status === "halftime"} />
    </div>
  )
}

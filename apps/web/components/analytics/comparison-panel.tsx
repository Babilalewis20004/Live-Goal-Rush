"use client"

import { useAsync } from "@/hooks/use-async"
import { LockedNote } from "@/components/analytics/premium-gate"
import { FormStrip } from "@/components/match-centre/form-strip"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { comparisonShares, formatNumber, leader, rowSummary } from "@/lib/analytics"
import type { ComparisonRow, MatchComparisonOut } from "@/types/api"

const CARD = "rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md"

function Row({ row, names }: { row: ComparisonRow; names: { home: string; away: string } }) {
  const shares = comparisonShares(row)
  const side = leader(row)
  return (
    <li className="py-2" aria-label={rowSummary(row, names)}>
      <div className="flex items-baseline justify-between text-sm">
        <span className={`w-16 text-left font-semibold tabular-nums ${side === "home" ? "text-emerald-300" : "text-white/80"}`}>{formatNumber(row.home)}</span>
        <span className="flex-1 px-2 text-center text-xs text-white/60">{row.label}</span>
        <span className={`w-16 text-right font-semibold tabular-nums ${side === "away" ? "text-emerald-300" : "text-white/80"}`}>{formatNumber(row.away)}</span>
      </div>
      {shares && (
        <div className="mt-1 flex h-1.5 gap-0.5" aria-hidden>
          <div className="flex justify-end overflow-hidden rounded-l-full bg-white/10" style={{ width: `${shares.home}%` }}>
            <div className={`h-full w-full ${side === "home" ? "bg-emerald-400" : "bg-white/30"}`} />
          </div>
          <div className="overflow-hidden rounded-r-full bg-white/10" style={{ width: `${shares.away}%` }}>
            <div className={`h-full w-full ${side === "away" ? "bg-emerald-400" : "bg-white/30"}`} />
          </div>
        </div>
      )}
      {(row.home === null || row.away === null) && (
        <p className="mt-0.5 text-center text-[11px] text-white/60">Not enough data for one side.</p>
      )}
    </li>
  )
}

export function ComparisonView({ data, signedIn }: { data: MatchComparisonOut; signedIn: boolean }) {
  const names = { home: data.home_team.name, away: data.away_team.name }
  return (
    <section className={CARD} aria-labelledby="comparison-heading">
      <div className="flex items-baseline justify-between">
        <h2 id="comparison-heading" className="text-sm font-semibold text-white">
          Team comparison
        </h2>
        <span className="text-[11px] text-white/60">Last {data.form_window} matches before kick-off</span>
      </div>
      <div className="mt-2 flex justify-between text-xs font-medium text-white/70">
        <span>{names.home}</span>
        <span>{names.away}</span>
      </div>

      {(data.home_form || data.away_form) && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {data.home_form && <FormLine title={names.home} sequence={data.home_sequence} summary={data.home_form} />}
          {data.away_form && <FormLine title={names.away} sequence={data.away_sequence} summary={data.away_form} />}
        </div>
      )}

      <ul className="mt-2 divide-y divide-white/[0.06]">
        {data.rows.map((r) => (
          <Row key={r.key} row={r} names={names} />
        ))}
      </ul>

      {data.head_to_head && data.head_to_head.total_meetings ? (
        <p className="mt-3 text-xs text-white/60">
          Head to head ({data.head_to_head.total_meetings} meetings): {names.home} {data.head_to_head.home_team_wins} wins, {data.head_to_head.draws} draws, {names.away}{" "}
          {data.head_to_head.away_team_wins} wins
          {data.head_to_head.average_goals !== null && data.head_to_head.average_goals !== undefined ? `; ${formatNumber(data.head_to_head.average_goals)} goals per game` : ""}.
        </p>
      ) : null}

      <LockedNote locked={data.locked} signedIn={signedIn} />
      {data.limitations.map((l) => (
        <p key={l} className="mt-2 text-[11px] text-white/60">
          Note: {l}
        </p>
      ))}
    </section>
  )
}

function FormLine({ title, sequence, summary }: { title: string; sequence: string; summary: NonNullable<MatchComparisonOut["home_form"]> }) {
  return (
    <div>
      <p className="text-xs font-medium text-white/70">{title}</p>
      <p className="mt-1 font-mono text-sm tracking-widest text-white" aria-label={`Form, oldest to newest: ${sequence.split("").join(", ")}`}>
        {sequence || NO_FORM}
      </p>
      <p className="text-[11px] text-white/60">
        {summary.wins}W {summary.draws}D {summary.losses}L · {summary.goals_for}–{summary.goals_against} goals
        {summary.limitation ? ` · ${summary.limitation}` : ""}
      </p>
    </div>
  )
}
const NO_FORM = "no recent matches"

export function ComparisonPanel({ matchId, nudge = 0 }: { matchId: number; nudge?: number }) {
  const { user } = useAuth()
  const { data, error, loading } = useAsync(() => api.getMatchComparison(matchId), `comparison:${matchId}:${user?.id ?? "anon"}`, nudge)
  if (loading && !data) return <section className={CARD} aria-busy="true"><p className="text-xs text-white/60">Loading comparison…</p></section>
  if (error || !data) {
    return (
      <section className={CARD}>
        <h2 className="text-sm font-semibold text-white">Team comparison</h2>
        <p className="mt-2 text-xs text-white/60">The comparison isn&apos;t available right now.</p>
      </section>
    )
  }
  return <ComparisonView data={data} signedIn={!!user} />
}

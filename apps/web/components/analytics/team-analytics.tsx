"use client"

import { useState } from "react"

import { LockedNote } from "@/components/analytics/premium-gate"
import { PremiumGate } from "@/components/analytics/premium-gate"
import { useAsync, isPaymentRequired } from "@/hooks/use-async"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { coverage, formatStat, timeAgo } from "@/lib/analytics"
import type { Stat, TeamAnalyticsOut } from "@/types/api"

const CARD = "rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md"

const LABELS: Record<string, { label: string; suffix?: string; digits?: number }> = {
  goals: { label: "Goals" },
  goals_per_match: { label: "Goals per match", digits: 2 },
  shots: { label: "Shots" },
  shots_per_match: { label: "Shots per match", digits: 1 },
  shots_on_target: { label: "Shots on target" },
  shot_conversion_pct: { label: "Shot conversion", suffix: "%" },
  expected_goals: { label: "Expected goals (xG)", digits: 1 },
  expected_goals_per_match: { label: "xG per match", digits: 2 },
  assists: { label: "Assists" },
  chances_created: { label: "Chances created" },
  possession_pct: { label: "Average possession", suffix: "%" },
  pass_accuracy_pct: { label: "Pass accuracy", suffix: "%" },
  passes: { label: "Passes" },
  goals_conceded: { label: "Goals conceded" },
  goals_conceded_per_match: { label: "Conceded per match", digits: 2 },
  clean_sheets: { label: "Clean sheets" },
  tackles: { label: "Tackles" },
  interceptions: { label: "Interceptions" },
  clearances: { label: "Clearances" },
  blocks: { label: "Blocks" },
  yellow_cards: { label: "Yellow cards" },
  red_cards: { label: "Red cards" },
  fouls: { label: "Fouls" },
}

function Section({ title, stats, matches }: { title: string; stats: Record<string, Stat>; matches: number }) {
  const entries = Object.entries(stats)
  if (entries.length === 0) return null
  return (
    <section aria-label={title}>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">{title}</h3>
      <dl className="divide-y divide-white/[0.05] rounded-xl border border-white/[0.06]">
        {entries.map(([key, stat]) => {
          const meta = LABELS[key] ?? { label: key.replaceAll("_", " ") }
          const partial = coverage(stat, matches)
          return (
            <div key={key} className="flex items-baseline justify-between gap-3 px-3 py-1.5 text-sm">
              <dt className="text-white/60">{meta.label}</dt>
              <dd className="text-right font-semibold tabular-nums text-white">
                {formatStat(stat, { suffix: meta.suffix, digits: meta.digits })}
                {partial && <span className="ml-2 text-[11px] font-normal text-white/60">{partial}</span>}
                {stat.value === null && <span className="sr-only"> (not provided by the data source)</span>}
              </dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}

export function TeamAnalyticsView({ data, signedIn }: { data: TeamAnalyticsOut; signedIn: boolean }) {
  const r = data.record
  const updated = timeAgo(data.generated_at)
  return (
    <div className="space-y-4">
      <section aria-label="Record">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">
          Record · last {data.matches_considered} {data.scope === "overall" ? "" : `${data.scope} `}matches
        </h3>
        <p className="text-sm text-white/80">
          <strong className="text-white">{r.wins}</strong> won, <strong className="text-white">{r.draws}</strong> drawn, <strong className="text-white">{r.losses}</strong> lost ·{" "}
          {r.points} points{r.points_per_match !== null ? ` (${r.points_per_match} per match)` : ""}
        </p>
      </section>
      <Section title="Attack" stats={data.attack} matches={data.matches_considered} />
      <Section title="Possession & passing" stats={data.possession} matches={data.matches_considered} />
      <Section title="Defence" stats={data.defence} matches={data.matches_considered} />
      <Section title="Discipline" stats={data.discipline} matches={data.matches_considered} />
      <LockedNote locked={data.locked} signedIn={signedIn} />
      {data.unavailable.length > 0 && (
        <p className="text-[11px] text-white/60">Not tracked by this platform: {data.unavailable.map((u) => u.replaceAll("_", " ")).join(", ")}.</p>
      )}
      {data.limitations.map((l) => (
        <p key={l} className="text-[11px] text-amber-200/70">
          {l}
        </p>
      ))}
      <p className="text-[11px] text-white/60">Calculated from stored results and match statistics{updated ? ` · updated ${updated}` : ""}.</p>
    </div>
  )
}

const SCOPES = ["overall", "home", "away"] as const
const WINDOWS = [5, 10, 20, 38] as const

/** Team analytics tab. The default view (last 10, overall) is free in its basic form; longer
 * windows are Premium and the server answers 402 for them -- we then say why, we don't hide the error. */
export function TeamAnalytics({ teamId }: { teamId: number }) {
  const { user } = useAuth()
  const [scope, setScope] = useState<(typeof SCOPES)[number]>("overall")
  const [window, setWindow] = useState<(typeof WINDOWS)[number]>(10)
  const { data, error, loading } = useAsync(() => api.getTeamAnalytics(teamId, { scope, window }), `team-analytics:${teamId}:${scope}:${window}:${user?.id ?? "anon"}`)

  return (
    <div className={CARD}>
      <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="Analytics options">
        {SCOPES.map((s) => (
          <button key={s} type="button" aria-pressed={scope === s} onClick={() => setScope(s)}
            className={`rounded-full border px-3 py-1 text-xs capitalize ${scope === s ? "border-emerald-400/60 bg-emerald-400/15 text-white" : "border-white/10 text-white/60 hover:text-white"}`}>
            {s}
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-white/10" aria-hidden />
        {WINDOWS.map((w) => (
          <button key={w} type="button" aria-pressed={window === w} onClick={() => setWindow(w)}
            className={`rounded-full border px-3 py-1 text-xs ${window === w ? "border-emerald-400/60 bg-emerald-400/15 text-white" : "border-white/10 text-white/60 hover:text-white"}`}>
            Last {w}{w > 10 ? " 🔒" : ""}
          </button>
        ))}
      </div>

      {loading && !data && <p className="text-xs text-white/60" aria-busy="true">Loading analytics…</p>}
      {isPaymentRequired(error) ? (
        <PremiumGate title="Longer history" items={["Last 20 and last 38 matches", "Extended form and head-to-head"]} signedIn={!!user} />
      ) : error && !data ? (
        <p className="text-xs text-white/60">Analytics aren&apos;t available right now.</p>
      ) : (
        data && <TeamAnalyticsView data={data} signedIn={!!user} />
      )}
    </div>
  )
}

"use client"

import { useState } from "react"
import Link from "next/link"
import { FeatureState } from "@/components/ui/feature-state"
import { EmptyState } from "@/components/ui/empty-state"
import { TabPanel, Tabs, type TabDef } from "@/components/ui/tabs"
import { FormStrip } from "@/components/match-centre/form-strip"
import { MatchCard } from "@/components/match-card"
import type {
  Capabilities,
  MatchSummary,
  PlayerOut,
  TeamDetail,
  TeamFormOut,
  TeamStatisticsOut,
} from "@/types/api"

type TabId = "overview" | "fixtures" | "results" | "squad" | "stats"

const TABS: TabDef<TabId>[] = [
  { id: "overview", label: "Overview" },
  { id: "fixtures", label: "Fixtures" },
  { id: "results", label: "Results" },
  { id: "squad", label: "Squad" },
  { id: "stats", label: "Statistics" },
]

const ID_PREFIX = "team"
const CARD = "overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"

function MatchList({ matches, empty }: { matches: MatchSummary[]; empty: string }) {
  if (matches.length === 0) return <EmptyState message={empty} />
  return (
    <div className={`${CARD} divide-y divide-white/[0.06]`}>
      {matches.map((m) => (
        <MatchCard key={m.id} match={m} />
      ))}
    </div>
  )
}

export interface TeamCentreData {
  team: TeamDetail
  fixtures: MatchSummary[]
  results: MatchSummary[]
  form: { overall: TeamFormOut | null; home: TeamFormOut | null; away: TeamFormOut | null }
  squad: PlayerOut[] | null
  statistics: TeamStatisticsOut | null
  capabilities: Capabilities | null
}

/** Team page body. Data is loaded server-side (app/team/[id]/page.tsx); the
 * tabs are client-only state. Live matches here link through to the match
 * centre, which owns the real-time feed. */
export function TeamCentre({ data }: { data: TeamCentreData }) {
  const [tab, setTab] = useState<TabId>("overview")
  const { team, fixtures, results, form, squad, statistics, capabilities } = data

  return (
    <div>
      <Tabs tabs={TABS} active={tab} onChange={setTab} idPrefix={ID_PREFIX} label="Team sections" />

      <TabPanel idPrefix={ID_PREFIX} id="overview" active={tab === "overview"}>
        <div className="space-y-4">
          <section className={`${CARD} p-4`}>
            <h2 className="mb-3 text-sm font-semibold text-white">Form</h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {form.overall ? <FormStrip form={form.overall} title="Overall" /> : null}
              {form.home ? <FormStrip form={form.home} title="Home" /> : null}
              {form.away ? <FormStrip form={form.away} title="Away" /> : null}
            </div>
            <p className="mt-3 text-[10px] text-white/30">Historical results, not a prediction.</p>
          </section>
          {team.venue && (
            <section className={`${CARD} px-4 py-3 text-sm text-white/70`}>
              <span className="text-white/40">Stadium </span>
              {team.venue}
            </section>
          )}
          {team.competitions.length > 0 && (
            <section className={`${CARD} p-4`}>
              <h2 className="mb-2 text-sm font-semibold text-white">Competitions</h2>
              <ul className="flex flex-wrap gap-2">
                {team.competitions.map((c) => (
                  <li key={c.id}>
                    <Link
                      href={`/competition/${c.id}`}
                      className="rounded-lg bg-white/[0.06] px-3 py-1.5 text-xs text-white/80 hover:bg-white/[0.1]"
                    >
                      {c.name}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section className={CARD}>
            <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">Next match</h2>
            {fixtures[0] ? <MatchCard match={fixtures[0]} /> : <p className="px-4 py-4 text-xs text-white/40">No upcoming fixtures.</p>}
          </section>
        </div>
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="fixtures" active={tab === "fixtures"}>
        <MatchList matches={fixtures} empty="No upcoming fixtures." />
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="results" active={tab === "results"}>
        <MatchList matches={results} empty="No recent results." />
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="squad" active={tab === "squad"}>
        {squad && squad.length > 0 ? (
          <section className={CARD}>
            <ul className="divide-y divide-white/[0.05] px-4">
              {squad.map((p) => (
                <li key={p.id}>
                  <Link href={`/player/${p.id}`} className="flex items-center gap-3 py-2.5 text-sm text-white/85 hover:text-white">
                    <span className="w-6 shrink-0 text-right text-xs font-semibold tabular-nums text-white/45">
                      {p.shirt_number ?? "–"}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{p.name}</span>
                    <span className="shrink-0 text-[11px] text-white/40">{p.position ?? ""}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <FeatureState
            feature="team_squads"
            capabilities={capabilities}
            pendingMessage="The squad is still being loaded. Check back in a moment."
          />
        )}
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="stats" active={tab === "stats"}>
        {statistics && statistics.seasons.length > 0 ? (
          <div className="space-y-4">
            {statistics.seasons.map((s) => (
              <section key={`${s.competition_id}-${s.season}-${s.group}`} className={`${CARD} p-4`}>
                <div className="mb-3 flex items-baseline justify-between">
                  <h2 className="text-sm font-semibold text-white">
                    <Link href={`/competition/${s.competition_id}`} className="hover:underline">
                      {s.competition_name}
                    </Link>
                    {s.group ? ` · ${s.group}` : ""}
                  </h2>
                  <span className="text-[11px] text-white/45">Season {s.season}</span>
                </div>
                <dl className="grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
                  {[
                    ["Position", s.position],
                    ["Played", s.played],
                    ["Won", s.won],
                    ["Drawn", s.drawn],
                    ["Lost", s.lost],
                    ["Points", s.points],
                    ["Goals for", s.goals_for],
                    ["Goals against", s.goals_against],
                    ["Goal diff.", s.goal_difference > 0 ? `+${s.goal_difference}` : s.goal_difference],
                  ].map(([label, value]) => (
                    <div key={String(label)} className="rounded-lg bg-white/[0.04] px-2 py-2">
                      <dd className="text-base font-bold tabular-nums text-white">{value}</dd>
                      <dt className="text-[10px] text-white/45">{label}</dt>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
            <p className="text-[10px] text-white/30">
              Taken from each competition&apos;s official table. Clean sheets and other derived figures aren&apos;t
              shown because the data provider doesn&apos;t supply them.
            </p>
          </div>
        ) : (
          <EmptyState message="No season statistics are available for this team yet." />
        )}
      </TabPanel>
    </div>
  )
}

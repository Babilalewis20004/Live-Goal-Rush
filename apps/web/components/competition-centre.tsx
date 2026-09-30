"use client"

import { useState } from "react"
import Link from "next/link"
import { EmptyState } from "@/components/ui/empty-state"
import { FeatureState } from "@/components/ui/feature-state"
import { TabPanel, Tabs, type TabDef } from "@/components/ui/tabs"
import { MatchCard } from "@/components/match-card"
import { TeamBadge } from "@/components/team-badge"
import { StandingsTable } from "@/components/match-centre/standings-table"
import { TopScorers } from "@/components/match-centre/top-scorers"
import type { Capabilities, MatchSummary, StandingEntry, TeamOut, TopScorersOut } from "@/types/api"

type TabId = "standings" | "fixtures" | "results" | "scorers" | "teams"

const TABS: TabDef<TabId>[] = [
  { id: "standings", label: "Standings" },
  { id: "fixtures", label: "Fixtures" },
  { id: "results", label: "Results" },
  { id: "scorers", label: "Top scorers" },
  { id: "teams", label: "Teams" },
]

const ID_PREFIX = "competition"
const CARD = "overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"

export interface CompetitionCentreData {
  standings: StandingEntry[] | null
  fixtures: MatchSummary[]
  results: MatchSummary[]
  topScorers: TopScorersOut | null
  capabilities: Capabilities | null
}

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

export function CompetitionCentre({ data }: { data: CompetitionCentreData }) {
  const [tab, setTab] = useState<TabId>("standings")
  const { standings, fixtures, results, topScorers, capabilities } = data

  // Teams come from the table (every team has a row); no separate endpoint.
  const teams: TeamOut[] = []
  const seen = new Set<number>()
  for (const row of standings ?? []) {
    if (!seen.has(row.team.id)) {
      seen.add(row.team.id)
      teams.push(row.team)
    }
  }
  teams.sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div>
      <Tabs tabs={TABS} active={tab} onChange={setTab} idPrefix={ID_PREFIX} label="Competition sections" />

      <TabPanel idPrefix={ID_PREFIX} id="standings" active={tab === "standings"}>
        {standings && standings.length > 0 ? (
          <StandingsTable standings={standings} />
        ) : (
          <FeatureState feature="standings" capabilities={capabilities} pendingMessage="No table is available yet." />
        )}
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="fixtures" active={tab === "fixtures"}>
        <MatchList matches={fixtures} empty="No fixtures available." />
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="results" active={tab === "results"}>
        <MatchList matches={results} empty="No results available." />
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="scorers" active={tab === "scorers"}>
        {topScorers && topScorers.scorers.length > 0 ? (
          <TopScorers data={topScorers} />
        ) : (
          <FeatureState
            feature="top_scorers"
            capabilities={capabilities}
            pendingMessage="Top scorers aren't available for this competition yet."
          />
        )}
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="teams" active={tab === "teams"}>
        {teams.length > 0 ? (
          <ul className="grid gap-2 sm:grid-cols-2">
            {teams.map((team) => (
              <li key={team.id}>
                <Link
                  href={`/team/${team.id}`}
                  className="flex items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06]"
                >
                  <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} />
                  <span className="truncate text-sm text-white">{team.name}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState message="No teams to show yet." />
        )}
      </TabPanel>
    </div>
  )
}

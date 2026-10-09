"use client"

import { useState } from "react"
import Link from "next/link"
import { AnalysisTab } from "@/components/analytics/analysis-tab"
import { Discuss } from "@/components/community/discuss"
import { FavouriteButton } from "@/components/favourite-button"
import { InsightsList } from "@/components/insights/insights-list"
import { EntityNews } from "@/components/news/entity-news"
import { ShareButton } from "@/components/news/share-button"
import { ConnectionBadge } from "@/components/ui/connection-badge"
import { FeatureState } from "@/components/ui/feature-state"
import { TabPanel, Tabs, type TabDef } from "@/components/ui/tabs"
import { FormStrip } from "@/components/match-centre/form-strip"
import { HeadToHead } from "@/components/match-centre/head-to-head"
import { Lineups } from "@/components/match-centre/lineups"
import { LiveAnnouncer, StaleBanner } from "@/components/match-centre/live-status"
import { MatchHeader } from "@/components/match-centre/match-header"
import { StandingsTable } from "@/components/match-centre/standings-table"
import { Statistics, hasStatistics } from "@/components/match-centre/statistics"
import { Timeline } from "@/components/match-centre/timeline"
import { useMatchDetail } from "@/hooks/use-match-detail"
import type {
  ArticleSummary,
  Capabilities,
  HeadToHeadOut,
  MatchInsightsOut,
  MatchDetail as MatchDetailType,
  MatchFormOut,
  MatchLineupsOut,
  MatchStatisticsOut,
  Page,
  StandingEntry,
} from "@/types/api"

type TabId = "overview" | "analysis" | "timeline" | "stats" | "lineups" | "table" | "news" | "discuss"

const TABS: TabDef<TabId>[] = [
  { id: "overview", label: "Overview" },
  { id: "analysis", label: "Analysis" },
  { id: "timeline", label: "Timeline" },
  { id: "stats", label: "Stats" },
  { id: "lineups", label: "Lineups" },
  { id: "table", label: "Table" },
]

const ID_PREFIX = "match"

/** Everything the server component loaded for first paint. Each piece other
 * than `match` is nullable: one failing/unsupported resource degrades to an
 * honest empty state for that tab instead of failing the whole page. */
export interface MatchCentreData {
  lineups: MatchLineupsOut | null
  statistics: MatchStatisticsOut | null
  form: MatchFormOut | null
  headToHead: HeadToHeadOut | null
  standings: StandingEntry[] | null
  capabilities: Capabilities | null
  /** News about this match, then its teams, then its competition (the API labels which). */
  news: Page<ArticleSummary> | null
  /** Form summaries, streaks and head-to-head sentences (null if unavailable). */
  insights: MatchInsightsOut | null
  /** Canonical absolute URL, for sharing. */
  shareUrl: string
}

/** Client half of the match centre. The server component
 * (`app/match/[id]/page.tsx`) does the initial REST fetches so the page renders
 * real data on first load / with JS disabled; this takes over with
 * `useMatchDetail`'s single WebSocket feed. */
export function MatchDetailLive({
  initialMatch,
  initialFollowed = false,
  data,
}: {
  initialMatch: MatchDetailType
  initialFollowed?: boolean
  data: MatchCentreData
}) {
  const { match, connectionStatus, lastUpdatedAt, lineups, statistics, standings, nudges } = useMatchDetail(
    initialMatch,
    { lineups: data.lineups, statistics: data.statistics, standings: data.standings },
    data.capabilities,
  )
  const [tab, setTab] = useState<TabId>("overview")
  const isLive = match.status === "live" || match.status === "halftime"
  const notStarted = match.status === "scheduled" || match.status === "postponed" || match.status === "cancelled"
  const { capabilities, news } = data
  const tabs: TabDef<TabId>[] = [...TABS, ...(news && news.total > 0 ? [{ id: "news" as const, label: "News" }] : []), { id: "discuss", label: "Discuss" }]

  return (
    <div className="mx-auto max-w-3xl px-4 pb-16 pt-6">
      <div className="flex items-center justify-between">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>
        <div className="flex items-center gap-2">
          <ConnectionBadge status={connectionStatus} />
          <ShareButton url={data.shareUrl} title={`${match.home_team.name} vs ${match.away_team.name}`} />
          <FavouriteButton kind="match" id={match.id} initialFollowed={initialFollowed} />
        </div>
      </div>

      <div className="mt-4">
        <MatchHeader match={match} />
        <LiveAnnouncer match={match} />
        <StaleBanner status={connectionStatus} isLive={isLive} lastUpdatedAt={lastUpdatedAt} />
      </div>

      <div className="mt-4">
        <Tabs tabs={tabs} active={tab} onChange={setTab} idPrefix={ID_PREFIX} label="Match centre sections" />
      </div>

      <TabPanel idPrefix={ID_PREFIX} id="overview" active={tab === "overview"}>
        <div className="space-y-4">
          <section className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md">
            <h2 className="mb-3 text-sm font-semibold text-white">Form</h2>
            {data.form ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <FormStrip form={data.form.home} title={match.home_team.name} />
                <FormStrip form={data.form.away} title={match.away_team.name} />
              </div>
            ) : (
              <p className="text-xs text-white/40">Form isn&apos;t available right now.</p>
            )}
            <p className="mt-3 text-[10px] text-white/30">
              Results before this match only. Historical information, not a prediction.
            </p>
          </section>

          <section className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md">
            {data.headToHead ? (
              <HeadToHead match={match} data={data.headToHead} />
            ) : (
              <p className="text-xs text-white/40">Head-to-head isn&apos;t available right now.</p>
            )}
          </section>

          {data.insights && (data.insights.home.insights.length > 0 || data.insights.away.insights.length > 0 || data.insights.head_to_head.length > 0) && (
            <section className="space-y-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md">
              <h2 className="text-sm font-semibold text-white">Form &amp; streaks</h2>
              <InsightsList title={match.home_team.name} insights={data.insights.home.insights} />
              <InsightsList title={match.away_team.name} insights={data.insights.away.insights} />
              <InsightsList title="Head to head" insights={data.insights.head_to_head} />
              <p className="text-[10px] text-white/30">{data.insights.note}</p>
            </section>
          )}

          {match.events.length > 0 && <Timeline match={match} />}
        </div>
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="analysis" active={tab === "analysis"}>
        <AnalysisTab match={match} nudges={nudges} />
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="timeline" active={tab === "timeline"}>
        {match.events.length > 0 ? (
          <Timeline match={match} />
        ) : (
          <FeatureState
            feature="match_events"
            capabilities={capabilities}
            pendingMessage={
              notStarted ? "The timeline starts at kick-off." : "No events have been recorded for this match."
            }
          />
        )}
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="stats" active={tab === "stats"}>
        {hasStatistics(statistics) ? (
          <Statistics match={match} statistics={statistics} />
        ) : (
          <FeatureState
            feature="match_statistics"
            capabilities={capabilities}
            pendingMessage={
              notStarted ? "Statistics appear once the match is under way." : "No statistics have been supplied for this match."
            }
          />
        )}
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="lineups" active={tab === "lineups"}>
        {lineups && (lineups.home || lineups.away) ? (
          <Lineups home={lineups.home} away={lineups.away} />
        ) : (
          <FeatureState
            feature="lineups"
            capabilities={capabilities}
            pendingMessage={
              notStarted
                ? "Lineups are usually published about an hour before kick-off."
                : "Lineups haven't been published for this match."
            }
          />
        )}
      </TabPanel>

      <TabPanel idPrefix={ID_PREFIX} id="table" active={tab === "table"}>
        {standings && standings.length > 0 ? (
          <StandingsTable
            standings={standings}
            highlightTeamIds={[match.home_team.id, match.away_team.id]}
            title={`${match.competition.name} table`}
          />
        ) : (
          <FeatureState
            feature="standings"
            capabilities={capabilities}
            pendingMessage="No table is available for this competition yet."
          />
        )}
      </TabPanel>

      {news && news.total > 0 && (
        <TabPanel idPrefix={ID_PREFIX} id="news" active={tab === "news"}>
          <EntityNews kind="match" id={match.id} initial={news} />
        </TabPanel>
      )}
      <TabPanel idPrefix={ID_PREFIX} id="discuss" active={tab === "discuss"}>
        <Discuss targetType="match" targetId={match.id} />
      </TabPanel>
    </div>
  )
}

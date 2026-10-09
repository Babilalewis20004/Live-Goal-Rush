import { useLocalSearchParams } from "expo-router"
import { AnalysisTab } from "@/components/analytics/analysis-tab"
import { Discuss } from "@/components/community/discuss"
import { InsightsBlock } from "@/components/insights-card"
import { EntityNews } from "@/components/news/entity-news"
import { ShareButton } from "@/components/news/share-button"
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { FlatList, RefreshControl, StyleSheet, Text, View } from "react-native"
import { ConnectionBadge } from "@/components/connection-badge"
import { ErrorState } from "@/components/error-state"
import { FavouriteButton } from "@/components/favourite-button"
import { LoadingState } from "@/components/loading-state"
import {
  HeadToHeadSection,
  LineupHeaderRow,
  LineupPlayerRow,
  MatchHeader,
  StandingRowView,
  StandingsHeaderRow,
  StandingsLegend,
  StatRowView,
  TimelineRow,
  buildTimeline,
} from "@/components/match-centre/rows"
import {
  Card,
  FeatureState,
  FormStrip,
  LiveAnnouncer,
  SectionTitle,
  StaleBanner,
  TabBar,
  type TabDef,
} from "@/components/match-centre/ui"
import { useAuth } from "@/hooks/use-auth"
import { useMatchDetail } from "@/hooks/use-match-detail"
import { api, ApiError } from "@/lib/api"
import { groupStandings, statRows } from "@/lib/match-centre"
import { theme } from "@/theme"
import type {
  ArticleSummary,
  Capabilities,
  HeadToHeadOut,
  MatchDetail,
  MatchFormOut,
  MatchInsightsOut,
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

interface Loaded {
  match: MatchDetail
  capabilities: Capabilities | null
  lineups: MatchLineupsOut | null
  statistics: MatchStatisticsOut | null
  form: MatchFormOut | null
  headToHead: HeadToHeadOut | null
  standings: StandingEntry[] | null
  news: Page<ArticleSummary> | null
  insights: MatchInsightsOut | null
}

/** The supplementary resources may each fail on their own (that tab shows an
 * honest empty state); only the match itself is essential. */
async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

export default function MatchScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { user } = useAuth()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [initialFollowed, setInitialFollowed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const matchId = Number(id)
      const match = await api.getMatch(matchId)
      const [capabilities, lineups, statistics, form, headToHead, standings, favourites, news, insights] = await Promise.all([
        optional(api.getCapabilities()),
        optional(api.getMatchLineups(matchId)),
        optional(api.getMatchStatistics(matchId)),
        optional(api.getMatchForm(matchId)),
        optional(api.getMatchHeadToHead(matchId)),
        optional(api.getStandings(match.competition.id)),
        user ? api.getFavourites().catch(() => null) : Promise.resolve(null),
        optional(api.getMatchNews(matchId)),
        optional(api.getMatchInsights(matchId)),
      ])
      setLoaded({ match, capabilities, lineups, statistics, form, headToHead, standings, news, insights })
      setInitialFollowed(favourites?.matches.some((f) => f.match.id === matchId) ?? false)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Match not found." : "Unable to load this match.")
    } finally {
      setLoading(false)
    }
  }, [id, user])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading match…" />
      </View>
    )
  }

  if (error || !loaded) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this match."} onRetry={load} />
      </View>
    )
  }

  return <MatchCentre loaded={loaded} initialFollowed={initialFollowed} />
}

interface Row {
  key: string
  node: ReactNode
}

function MatchCentre({ loaded, initialFollowed }: { loaded: Loaded; initialFollowed: boolean }) {
  const { match, connectionStatus, lastUpdatedAt, lineups, statistics, standings, refresh, nudges } = useMatchDetail(
    loaded.match,
    { lineups: loaded.lineups, statistics: loaded.statistics, standings: loaded.standings },
    loaded.capabilities,
  )
  const { capabilities, form, headToHead } = loaded
  const [tab, setTab] = useState<TabId>("overview")
  const [refreshing, setRefreshing] = useState(false)
  const isLive = match.status === "live" || match.status === "halftime"
  const notStarted = match.status === "scheduled" || match.status === "postponed" || match.status === "cancelled"

  const onRefresh = useCallback(async () => {
    setRefreshing(true)
    await refresh()
    setRefreshing(false)
  }, [refresh])

  // Rows are built per tab so FlatList only mounts what's on screen (a
  // standings table or a squad can be dozens of rows); single-card tabs are
  // simply one row.
  const rows = useMemo<Row[]>(() => {
    const out: Row[] = []
    if (tab === "overview") {
      out.push({
        key: "form",
        node: (
          <Card>
            <SectionTitle>Form</SectionTitle>
            {form ? (
              <View style={{ gap: 14 }}>
                <FormStrip form={form.home} title={match.home_team.name} />
                <FormStrip form={form.away} title={match.away_team.name} />
              </View>
            ) : (
              <Text style={styles.faint}>Form isn&apos;t available right now.</Text>
            )}
            <Text style={[styles.faint, { marginTop: 10 }]}>
              Results before this match only. Historical information, not a prediction.
            </Text>
          </Card>
        ),
      })
      if (loaded.insights && (loaded.insights.home.insights.length || loaded.insights.away.insights.length || loaded.insights.head_to_head.length)) {
        out.push({
          key: "insights",
          node: (
            <Card>
              <SectionTitle>Form &amp; streaks</SectionTitle>
              <View style={{ gap: 14 }}>
                <InsightsBlock title={match.home_team.name} insights={loaded.insights.home.insights} />
                <InsightsBlock title={match.away_team.name} insights={loaded.insights.away.insights} />
                <InsightsBlock title="Head to head" insights={loaded.insights.head_to_head} />
              </View>
              <Text style={[styles.faint, { marginTop: 10 }]}>{loaded.insights.note}</Text>
            </Card>
          ),
        })
      }
      out.push({
        key: "h2h",
        node: (
          <Card>
            {headToHead ? (
              <HeadToHeadSection match={match} data={headToHead} />
            ) : (
              <Text style={styles.faint}>Head-to-head isn&apos;t available right now.</Text>
            )}
          </Card>
        ),
      })
    } else if (tab === "analysis") {
      out.push({ key: "analysis", node: <AnalysisTab match={match} nudges={nudges} /> })
    } else if (tab === "discuss") {
      out.push({ key: "discuss", node: <Discuss targetType="match" targetId={match.id} /> })
    } else if (tab === "news" && loaded.news) {
      out.push({ key: "news", node: <EntityNews kind="match" id={match.id} initial={loaded.news} /> })
    } else if (tab === "timeline") {
      const items = buildTimeline(match)
      if (items.length === 0) {
        out.push({
          key: "no-events",
          node: (
            <FeatureState
              feature="match_events"
              capabilities={capabilities}
              pendingMessage={notStarted ? "The timeline starts at kick-off." : "No events have been recorded for this match."}
            />
          ),
        })
      }
      for (const item of items) out.push({ key: `e-${item.id}`, node: <TimelineRow item={item} /> })
    } else if (tab === "stats") {
      const stats = statRows(statistics)
      if (stats.length === 0) {
        out.push({
          key: "no-stats",
          node: (
            <FeatureState
              feature="match_statistics"
              capabilities={capabilities}
              pendingMessage={notStarted ? "Statistics appear once the match is under way." : "No statistics have been supplied for this match."}
            />
          ),
        })
      }
      for (const row of stats) {
        out.push({
          key: row.key,
          node: <StatRowView row={row} homeName={match.home_team.name} awayName={match.away_team.name} />,
        })
      }
    } else if (tab === "lineups") {
      const sides = [lineups?.home, lineups?.away].filter((s): s is NonNullable<typeof s> => !!s)
      if (sides.length === 0) {
        out.push({
          key: "no-lineups",
          node: (
            <FeatureState
              feature="lineups"
              capabilities={capabilities}
              pendingMessage={
                notStarted
                  ? "Lineups are usually published about an hour before kick-off."
                  : "Lineups haven't been published for this match."
              }
            />
          ),
        })
      }
      for (const side of sides) {
        out.push({ key: `h-${side.team.id}`, node: <LineupHeaderRow lineup={side} /> })
        for (const p of side.starters) out.push({ key: `s-${side.team.id}-${p.player.id}`, node: <LineupPlayerRow entry={p} /> })
        if (side.substitutes.length > 0) {
          out.push({ key: `sl-${side.team.id}`, node: <Text style={styles.label}>Substitutes</Text> })
          for (const p of side.substitutes) out.push({ key: `b-${side.team.id}-${p.player.id}`, node: <LineupPlayerRow entry={p} /> })
        }
      }
    } else if (standings && standings.length > 0) {
      const highlight = [match.home_team.id, match.away_team.id]
      for (const { group, rows: groupRows } of groupStandings(standings)) {
        out.push({
          key: `th-${group}`,
          node: <StandingsHeaderRow group={group} season={groupRows[0]?.season ?? ""} />,
        })
        for (const row of groupRows) {
          out.push({
            key: `t-${group}-${row.team.id}`,
            node: <StandingRowView row={row} highlighted={highlight.includes(row.team.id)} />,
          })
        }
      }
      out.push({ key: "legend", node: <StandingsLegend standings={standings} /> })
    } else {
      out.push({
        key: "no-table",
        node: (
          <FeatureState feature="standings" capabilities={capabilities} pendingMessage="No table is available for this competition yet." />
        ),
      })
    }
    return out
  }, [tab, match, form, headToHead, statistics, lineups, standings, capabilities, notStarted, loaded.news, loaded.insights, nudges])

  const tabs: TabDef<TabId>[] = [...TABS, ...(loaded.news && loaded.news.total > 0 ? [{ id: "news" as const, label: "News" }] : []), { id: "discuss", label: "Discuss" }]

  const header = (
    <View style={{ gap: 12, marginBottom: 12 }}>
      <View style={styles.topRow}>
        <ConnectionBadge status={connectionStatus} />
        <FavouriteButton kind="match" id={match.id} initialFollowed={initialFollowed} />
      </View>
      <MatchHeader match={match} />
      <LiveAnnouncer match={match} />
      <StaleBanner status={connectionStatus} isLive={isLive} lastUpdatedAt={lastUpdatedAt} />
      <ShareButton kind="match" id={match.id} title={`${match.home_team.name} v ${match.away_team.name}`} />
      <TabBar tabs={tabs} active={tab} onChange={setTab} />
    </View>
  )

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={rows}
      keyExtractor={(row) => row.key}
      renderItem={({ item }) => <View style={tab === "overview" ? styles.rowGap : undefined}>{item.node}</View>}
      ListHeaderComponent={header}
      initialNumToRender={14}
      windowSize={7}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.emerald} />}
    />
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, paddingBottom: 48 },
  rowGap: { marginBottom: 12 },
  topRow: { flexDirection: "row", justifyContent: "flex-end", alignItems: "center", gap: 8 },
  faint: { color: theme.textFaint, fontSize: 11 },
  label: {
    color: theme.textFaint,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    paddingTop: 14,
    paddingBottom: 4,
  },
})

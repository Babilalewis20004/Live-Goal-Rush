import { useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { FlatList, StyleSheet, Text, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { FavouriteButton } from "@/components/favourite-button"
import { LoadingState } from "@/components/loading-state"
import { MatchCard } from "@/components/match-card"
import {
  StandingRowView,
  StandingsHeaderRow,
  StandingsLegend,
  TopScorerRow,
} from "@/components/match-centre/rows"
import { FeatureState, TabBar, type TabDef } from "@/components/match-centre/ui"
import { TeamBadge } from "@/components/team-badge"
import { useAuth } from "@/hooks/use-auth"
import { api, ApiError } from "@/lib/api"
import { groupStandings } from "@/lib/match-centre"
import { theme } from "@/theme"
import type { Capabilities, CompetitionOut, MatchSummary, StandingEntry, TopScorersOut } from "@/types/api"

type TabId = "standings" | "fixtures" | "results" | "scorers"

const TABS: TabDef<TabId>[] = [
  { id: "standings", label: "Standings" },
  { id: "fixtures", label: "Fixtures" },
  { id: "results", label: "Results" },
  { id: "scorers", label: "Top scorers" },
]

interface Loaded {
  competition: CompetitionOut
  standings: StandingEntry[] | null
  fixtures: MatchSummary[]
  results: MatchSummary[]
  topScorers: TopScorersOut | null
  capabilities: Capabilities | null
}

async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

export default function CompetitionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { user } = useAuth()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [initialFollowed, setInitialFollowed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabId>("standings")

  const load = useCallback(async () => {
    setError(null)
    try {
      const competitionId = Number(id)
      const [competition, fixtures, results, standings, topScorers, capabilities, favourites] = await Promise.all([
        api.getCompetition(competitionId),
        api.getCompetitionFixtures(competitionId, 1, 50, "upcoming"),
        api.getCompetitionFixtures(competitionId, 1, 50, "results"),
        optional(api.getStandings(competitionId)),
        optional(api.getTopScorers(competitionId)),
        optional(api.getCapabilities()),
        user ? api.getFavourites().catch(() => null) : Promise.resolve(null),
      ])
      setLoaded({ competition, standings, fixtures: fixtures.items, results: results.items, topScorers, capabilities })
      setInitialFollowed(favourites?.competitions.some((f) => f.competition.id === competitionId) ?? false)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Competition not found." : "Unable to load this competition.")
    } finally {
      setLoading(false)
    }
  }, [id, user])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  const rows = useMemo<{ key: string; node: ReactNode }[]>(() => {
    if (!loaded) return []
    const { standings, fixtures, results, topScorers, capabilities } = loaded
    const out: { key: string; node: ReactNode }[] = []
    if (tab === "standings") {
      if (standings && standings.length > 0) {
        for (const { group, rows: groupRows } of groupStandings(standings)) {
          out.push({ key: `th-${group}`, node: <StandingsHeaderRow group={group} season={groupRows[0]?.season ?? ""} /> })
          for (const row of groupRows) {
            out.push({ key: `t-${group}-${row.team.id}`, node: <StandingRowView row={row} /> })
          }
        }
        out.push({ key: "legend", node: <StandingsLegend standings={standings} /> })
      } else {
        out.push({
          key: "no-table",
          node: <FeatureState feature="standings" capabilities={capabilities} pendingMessage="No table is available yet." />,
        })
      }
    } else if (tab === "fixtures" || tab === "results") {
      const list = tab === "fixtures" ? fixtures : results
      if (list.length === 0) {
        out.push({ key: "empty", node: <EmptyState message={tab === "fixtures" ? "No fixtures available." : "No results available."} /> })
      }
      for (const m of list) out.push({ key: `m-${m.id}`, node: <MatchCard match={m} /> })
    } else if (topScorers && topScorers.scorers.length > 0) {
      out.push({
        key: "scorers-head",
        node: (
          <View style={styles.scorersHead}>
            <Text style={styles.faint}>Top scorers</Text>
            {topScorers.season && <Text style={styles.faint}>Season {topScorers.season}</Text>}
          </View>
        ),
      })
      for (const s of topScorers.scorers) out.push({ key: `s-${s.player.id}`, node: <TopScorerRow scorer={s} /> })
    } else {
      out.push({
        key: "no-scorers",
        node: (
          <FeatureState
            feature="top_scorers"
            capabilities={capabilities}
            pendingMessage="Top scorers aren't available for this competition yet."
          />
        ),
      })
    }
    return out
  }, [loaded, tab])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading competition…" />
      </View>
    )
  }

  if (error || !loaded) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this competition."} onRetry={load} />
      </View>
    )
  }

  const { competition } = loaded
  const header = (
    <View style={{ gap: 12, marginBottom: 12 }}>
      <View style={styles.headerCard}>
        <TeamBadge name={competition.name} logoUrl={competition.logo_url} size={44} />
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle} accessibilityRole="header">
            {competition.name}
          </Text>
          <Text style={styles.headerSubtitle}>
            {competition.country ?? "International"} · {competition.type}
          </Text>
        </View>
        <FavouriteButton kind="competition" id={competition.id} initialFollowed={initialFollowed} />
      </View>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
    </View>
  )

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={rows}
      keyExtractor={(row) => row.key}
      renderItem={({ item }) => <View>{item.node}</View>}
      ListHeaderComponent={header}
      initialNumToRender={14}
      windowSize={7}
    />
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, paddingBottom: 48 },
  headerCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
  },
  headerTitle: { color: theme.text, fontSize: 18, fontWeight: "800" },
  headerSubtitle: { color: theme.textFaint, fontSize: 12, marginTop: 2 },
  faint: { color: theme.textFaint, fontSize: 11 },
  scorersHead: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 8 },
})

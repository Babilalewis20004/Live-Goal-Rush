import { TeamAnalytics } from "@/components/analytics/team-analytics"
import { Link, useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { FavouriteButton } from "@/components/favourite-button"
import { LoadingState } from "@/components/loading-state"
import { MatchCard } from "@/components/match-card"
import { InsightsBlock } from "@/components/insights-card"
import { EntityNews } from "@/components/news/entity-news"
import { ShareButton } from "@/components/news/share-button"
import { SquadRow } from "@/components/match-centre/rows"
import { Card, FeatureState, FormStrip, SectionTitle, TabBar, type TabDef } from "@/components/match-centre/ui"
import { TeamBadge } from "@/components/team-badge"
import { useAuth } from "@/hooks/use-auth"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type {
  ArticleSummary,
  Capabilities,
  MatchSummary,
  Page,
  PlayerOut,
  TeamDetail,
  TeamFormOut,
  TeamInjuriesOut,
  TeamInsightsOut,
  TeamStatisticsOut,
} from "@/types/api"

type TabId = "overview" | "fixtures" | "results" | "squad" | "stats" | "analytics" | "news"

const TABS: TabDef<TabId>[] = [
  { id: "overview", label: "Overview" },
  { id: "fixtures", label: "Fixtures" },
  { id: "results", label: "Results" },
  { id: "squad", label: "Squad" },
  { id: "stats", label: "Statistics" },
  { id: "analytics", label: "Analytics" },
]

interface Loaded {
  team: TeamDetail
  fixtures: MatchSummary[]
  results: MatchSummary[]
  form: { overall: TeamFormOut | null; home: TeamFormOut | null; away: TeamFormOut | null }
  squad: PlayerOut[] | null
  statistics: TeamStatisticsOut | null
  capabilities: Capabilities | null
  news: Page<ArticleSummary> | null
  insights: TeamInsightsOut | null
  injuries: TeamInjuriesOut | null
}

async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

export default function TeamScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { user } = useAuth()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [initialFollowed, setInitialFollowed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabId>("overview")

  const load = useCallback(async () => {
    setError(null)
    try {
      const teamId = Number(id)
      const team = await api.getTeam(teamId)
      const [fixtures, results, overall, home, away, squad, statistics, capabilities, favourites, news, insights, injuries] = await Promise.all([
        api.getTeamFixtures(teamId),
        api.getTeamResults(teamId, 1, 20),
        optional(api.getTeamForm(teamId, "overall")),
        optional(api.getTeamForm(teamId, "home")),
        optional(api.getTeamForm(teamId, "away")),
        optional(api.getTeamSquad(teamId)),
        optional(api.getTeamStatistics(teamId)),
        optional(api.getCapabilities()),
        user ? api.getFavourites().catch(() => null) : Promise.resolve(null),
        optional(api.getTeamNews(teamId)),
        optional(api.getTeamInsights(teamId)),
        optional(api.getTeamInjuries(teamId)),
      ])
      setLoaded({
        team,
        fixtures: fixtures.items,
        results: results.items,
        form: { overall, home, away },
        squad,
        statistics,
        capabilities,
        news,
        insights,
        injuries,
      })
      setInitialFollowed(favourites?.teams.some((f) => f.team.id === teamId) ?? false)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Team not found." : "Unable to load this team.")
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
    const { team, fixtures, results, form, squad, statistics, capabilities } = loaded
    const out: { key: string; node: ReactNode }[] = []
    if (tab === "overview") {
      if (loaded.insights && loaded.insights.insights.length > 0) {
        out.push({
          key: "insights",
          node: (
            <Card>
              <SectionTitle>Form &amp; streaks</SectionTitle>
              <InsightsBlock title={`Last ${loaded.insights.sample_size} results`} insights={loaded.insights.insights} />
              <Text style={{ color: theme.textFaint, fontSize: 11, marginTop: 10 }}>Historical results only. Not a prediction.</Text>
            </Card>
          ),
        })
      }
      out.push({
        key: "form",
        node: (
          <Card>
            <SectionTitle>Form</SectionTitle>
            <View style={{ gap: 14 }}>
              {form.overall && <FormStrip form={form.overall} title="Overall" />}
              {form.home && <FormStrip form={form.home} title="Home" />}
              {form.away && <FormStrip form={form.away} title="Away" />}
            </View>
            <Text style={[styles.faint, { marginTop: 10 }]}>Historical results, not a prediction.</Text>
          </Card>
        ),
      })
      if (loaded.injuries?.supported && loaded.injuries.items.length > 0) {
        // Nothing is shown for an empty list: it would read as "no injuries".
        out.push({
          key: "injuries",
          node: (
            <Card>
              <SectionTitle>Injuries &amp; doubts</SectionTitle>
              {loaded.injuries.items.map((injury) => (
                <View
                  key={`${injury.player_name}-${injury.match_date}`}
                  style={styles.injuryRow}
                  accessible
                  accessibilityLabel={`${injury.player_name}, ${injury.kind === "missing" ? "out" : "doubtful"}${injury.reason ? `, ${injury.reason}` : ""}`}
                >
                  <Text style={styles.injuryName} numberOfLines={1}>
                    {injury.player_name}
                  </Text>
                  {injury.reason && (
                    <Text style={styles.faint} numberOfLines={1}>
                      {injury.reason}
                    </Text>
                  )}
                  <Text style={[styles.injuryBadge, injury.kind === "missing" ? styles.injuryOut : styles.injuryDoubtful]}>
                    {injury.kind === "missing" ? "Out" : "Doubtful"}
                  </Text>
                </View>
              ))}
              <Text style={[styles.faint, { marginTop: 10 }]}>
                Reported by the data provider; availability can change before kickoff.
              </Text>
            </Card>
          ),
        })
      }
      if (team.venue) {
        out.push({
          key: "venue",
          node: (
            <Card>
              <Text style={styles.faint}>Stadium</Text>
              <Text style={styles.body}>{team.venue}</Text>
            </Card>
          ),
        })
      }
      if (team.competitions.length > 0) {
        out.push({
          key: "competitions",
          node: (
            <Card>
              <SectionTitle>Competitions</SectionTitle>
              <View style={styles.chips}>
                {team.competitions.map((c) => (
                  <Link key={c.id} href={{ pathname: "/competition/[id]", params: { id: String(c.id) } }} asChild>
                    <Pressable style={styles.chip} accessibilityRole="link">
                      <Text style={styles.chipText}>{c.name}</Text>
                    </Pressable>
                  </Link>
                ))}
              </View>
            </Card>
          ),
        })
      }
      if (fixtures[0]) {
        out.push({
          key: "next",
          node: (
            <Card>
              <SectionTitle>Next match</SectionTitle>
              <MatchCard match={fixtures[0]} />
            </Card>
          ),
        })
      }
    } else if (tab === "analytics") {
      out.push({ key: "analytics", node: <TeamAnalytics teamId={team.id} /> })
    } else if (tab === "fixtures" || tab === "results") {
      const list = tab === "fixtures" ? fixtures : results
      if (list.length === 0) {
        out.push({
          key: "empty",
          node: <EmptyState message={tab === "fixtures" ? "No upcoming fixtures." : "No recent results."} />,
        })
      }
      for (const m of list) out.push({ key: `m-${m.id}`, node: <MatchCard match={m} /> })
    } else if (tab === "news" && loaded.news) {
      out.push({ key: "news", node: <EntityNews kind="team" id={team.id} initial={loaded.news} /> })
    } else if (tab === "squad") {
      if (!squad || squad.length === 0) {
        out.push({
          key: "no-squad",
          node: (
            <FeatureState
              feature="team_squads"
              capabilities={capabilities}
              pendingMessage="The squad is still being loaded. Pull to refresh in a moment."
            />
          ),
        })
      }
      for (const p of squad ?? []) out.push({ key: `p-${p.id}`, node: <SquadRow player={p} /> })
    } else if (statistics && statistics.seasons.length > 0) {
      for (const s of statistics.seasons) {
        out.push({
          key: `s-${s.competition_id}-${s.season}-${s.group}`,
          node: (
            <Card>
              <View style={styles.statHeader}>
                <Text style={styles.statTitle}>
                  {s.competition_name}
                  {s.group ? ` · ${s.group}` : ""}
                </Text>
                <Text style={styles.faint}>Season {s.season}</Text>
              </View>
              <View style={styles.statGrid}>
                {(
                  [
                    ["Pos", s.position],
                    ["P", s.played],
                    ["W", s.won],
                    ["D", s.drawn],
                    ["L", s.lost],
                    ["Pts", s.points],
                    ["GF", s.goals_for],
                    ["GA", s.goals_against],
                    ["GD", s.goal_difference > 0 ? `+${s.goal_difference}` : s.goal_difference],
                  ] as [string, string | number][]
                ).map(([label, value]) => (
                  <View key={label} style={styles.statCell} accessible accessibilityLabel={`${label}: ${value}`}>
                    <Text style={styles.statValue}>{value}</Text>
                    <Text style={styles.faint}>{label}</Text>
                  </View>
                ))}
              </View>
            </Card>
          ),
        })
      }
    } else {
      out.push({ key: "no-stats", node: <EmptyState message="No season statistics are available for this team yet." /> })
    }
    return out
  }, [loaded, tab])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading team…" />
      </View>
    )
  }

  if (error || !loaded) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this team."} onRetry={load} />
      </View>
    )
  }

  const { team } = loaded
  const tabs: TabDef<TabId>[] = loaded.news && loaded.news.total > 0 ? [...TABS, { id: "news", label: "News" }] : TABS
  const header = (
    <View style={{ gap: 12, marginBottom: 12 }}>
      <View style={styles.headerCard}>
        <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} size={44} />
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle} accessibilityRole="header">
            {team.name}
          </Text>
          {team.country && <Text style={styles.headerSubtitle}>{team.country}</Text>}
        </View>
        <FavouriteButton kind="team" id={team.id} initialFollowed={initialFollowed} />
      </View>
      <ShareButton kind="team" id={team.id} title={team.name} />
      <TabBar tabs={tabs} active={tab} onChange={setTab} />
    </View>
  )

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={rows}
      keyExtractor={(row) => row.key}
      renderItem={({ item }) => <View style={{ marginBottom: tab === "overview" || tab === "stats" ? 12 : 0 }}>{item.node}</View>}
      ListHeaderComponent={header}
      initialNumToRender={12}
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
  body: { color: theme.text, fontSize: 14, marginTop: 2 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { minHeight: 40, justifyContent: "center", paddingHorizontal: 14, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.07)" },
  chipText: { color: theme.text, fontSize: 13 },
  statHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 },
  statTitle: { color: theme.text, fontSize: 14, fontWeight: "700", flex: 1 },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  statCell: { width: "30%", alignItems: "center", paddingVertical: 8, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.05)" },
  injuryRow: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 40 },
  injuryName: { color: theme.text, fontSize: 14, flex: 1 },
  injuryBadge: { fontSize: 10, fontWeight: "700", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6, overflow: "hidden" },
  injuryOut: { color: "#fca5a5", backgroundColor: "rgba(239,68,68,0.15)" },
  injuryDoubtful: { color: "#fcd34d", backgroundColor: "rgba(245,158,11,0.15)" },
  statValue: { color: theme.text, fontSize: 16, fontWeight: "800" },
})

import { useCallback, useEffect, useMemo, useState } from "react"
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native"
import { LeagueSection } from "@/components/league-section"
import { LoadingState } from "@/components/loading-state"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { ConnectionBadge } from "@/components/connection-badge"
import { StaleBanner } from "@/components/stale-banner"
import { PersonalInsights } from "@/components/community/personal-insights"
import { DiscoverySections, ForYou } from "@/components/discovery-sections"
import { BOARD_CACHE_KEY, useLivescoreBoard } from "@/hooks/use-livescore-board"
import { useNow } from "@/hooks/use-now"
import { describeFreshness } from "@/lib/freshness"
import { groupByCompetition } from "@/lib/format"
import { loadCopy, saveCopy } from "@/lib/offline-cache"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type { MatchSummary } from "@/types/api"

type Filter = "live" | "today" | "upcoming" | "finished"

const FILTERS: { key: Filter; label: string }[] = [
  { key: "live", label: "Live" },
  { key: "today", label: "Today" },
  { key: "upcoming", label: "Upcoming" },
  { key: "finished", label: "Finished" },
]

export default function HomeScreen() {
  const [filter, setFilter] = useState<Filter>("live")
  const [initialLive, setInitialLive] = useState<MatchSummary[]>([])
  const [initialToday, setInitialToday] = useState<MatchSummary[]>([])
  const [initialUpcoming, setInitialUpcoming] = useState<MatchSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Set when the network failed and the on-device copy of the last good board is shown instead.
  const [savedAt, setSavedAt] = useState<number | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [liveData, todayData, upcomingData] = await Promise.all([
        api.getLiveMatches(),
        api.getTodayMatches(),
        api.getUpcomingMatches(),
      ])
      setInitialLive(liveData)
      setInitialToday(todayData)
      setInitialUpcoming(upcomingData)
      setSavedAt(null)
      void saveCopy(BOARD_CACHE_KEY, { live: liveData, today: todayData, upcoming: upcomingData })
    } catch (e) {
      const saved = await loadCopy<{ live: MatchSummary[]; today: MatchSummary[]; upcoming: MatchSummary[] }>(BOARD_CACHE_KEY)
      if (saved) {
        setInitialLive(saved.data.live)
        setInitialToday(saved.data.today)
        setInitialUpcoming(saved.data.upcoming)
        setSavedAt(saved.savedAt)
      } else {
        setError(e instanceof ApiError ? e.message : "Unable to load matches.")
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    // Deferred via setTimeout so the initial fetch's setState calls never
    // run synchronously within the effect (react-hooks/set-state-in-effect).
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  // Only mounted once the initial REST load has completed -- keeps the
  // WebSocket hook's seed data (and thus its match id set) from being
  // rebuilt out from under it by a background pull-to-refresh.
  return loading ? (
    <View style={styles.screen}>
      <LoadingState label="Loading matches…" />
    </View>
  ) : error ? (
    <View style={styles.screen}>
      <ErrorState message={error} onRetry={load} />
    </View>
  ) : (
    <LiveHomeScreen
      initialLive={initialLive}
      initialToday={initialToday}
      initialUpcoming={initialUpcoming}
      savedAt={savedAt}
      filter={filter}
      setFilter={setFilter}
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true)
        void load()
      }}
    />
  )
}

function LiveHomeScreen({
  initialLive,
  initialToday,
  initialUpcoming,
  savedAt,
  filter,
  setFilter,
  refreshing,
  onRefresh,
}: {
  initialLive: MatchSummary[]
  initialToday: MatchSummary[]
  initialUpcoming: MatchSummary[]
  savedAt: number | null
  filter: Filter
  setFilter: (f: Filter) => void
  refreshing: boolean
  onRefresh: () => void
}) {
  const board = useLivescoreBoard(initialLive, initialToday, initialUpcoming, savedAt)
  const now = useNow(5_000)
  const freshness = describeFreshness({
    connection: board.connectionStatus,
    lastUpdatedAt: board.lastUpdatedAt,
    now: now.getTime(),
    fromSavedCopy: board.showingSavedCopy,
    lastRefreshFailed: board.lastRefreshFailed,
  })

  const active = useMemo(() => {
    switch (filter) {
      case "live":
        return board.live
      case "today":
        return board.today
      case "upcoming":
        return board.upcoming
      case "finished":
        return board.finished
    }
  }, [filter, board])

  const groups = useMemo(() => groupByCompetition(active), [active])

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.emerald} />}
    >
      <View style={styles.headerRow}>
        <ConnectionBadge status={board.connectionStatus} />
      </View>
      <StaleBanner message={freshness.message} />

      <PersonalInsights />
      <ForYou />

      <View style={styles.tabs}>
        {FILTERS.map((f) => {
          const isActive = filter === f.key
          return (
            <Pressable
              key={f.key}
              onPress={() => setFilter(f.key)}
              style={[styles.tab, isActive && styles.tabActive]}
            >
              <Text style={[styles.tabText, isActive && styles.tabTextActive]}>{f.label}</Text>
            </Pressable>
          )
        })}
      </View>

      {groups.length === 0 ? (
        <EmptyState message="No matches in this category right now." />
      ) : (
        groups.map(({ competition, matches }) => (
          <LeagueSection key={competition.id} competition={competition} matches={matches} />
        ))
      )}

      <DiscoverySections />
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: theme.background,
  },
  content: {
    padding: 16,
  },
  headerRow: {
    marginBottom: 8,
  },
  tabs: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 16,
  },
  tab: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  tabActive: {
    backgroundColor: theme.emerald,
    borderColor: theme.emerald,
  },
  tabText: {
    color: theme.textMuted,
    fontSize: 13,
    fontWeight: "600",
  },
  tabTextActive: {
    color: theme.background,
  },
})

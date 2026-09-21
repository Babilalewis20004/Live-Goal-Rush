import { useCallback, useEffect, useMemo, useState } from "react"
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native"
import { LeagueSection } from "@/components/league-section"
import { LoadingState } from "@/components/loading-state"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { groupByCompetition } from "@/lib/format"
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
  const [live, setLive] = useState<MatchSummary[]>([])
  const [today, setToday] = useState<MatchSummary[]>([])
  const [upcoming, setUpcoming] = useState<MatchSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [liveData, todayData, upcomingData] = await Promise.all([
        api.getLiveMatches(),
        api.getTodayMatches(),
        api.getUpcomingMatches(),
      ])
      setLive(liveData)
      setToday(todayData)
      setUpcoming(upcomingData)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to load matches.")
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

  const finished = useMemo(() => today.filter((m) => m.status === "finished"), [today])

  const active = useMemo(() => {
    switch (filter) {
      case "live":
        return live
      case "today":
        return today
      case "upcoming":
        return upcoming
      case "finished":
        return finished
    }
  }, [filter, live, today, upcoming, finished])

  const groups = useMemo(() => groupByCompetition(active), [active])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading matches…" />
      </View>
    )
  }

  if (error) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error} onRetry={load} />
      </View>
    )
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load() }} tintColor={theme.emerald} />}
    >
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

import { useCallback, useEffect, useState } from "react"
import { Link } from "expo-router"
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { TeamBadge } from "@/components/team-badge"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type { CompetitionOut } from "@/types/api"

export default function CompetitionsScreen() {
  const [competitions, setCompetitions] = useState<CompetitionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const { items } = await api.getCompetitions()
      setCompetitions(items)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to load competitions.")
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading competitions…" />
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
      {competitions.length === 0 ? (
        <EmptyState message="No competitions available." />
      ) : (
        competitions.map((competition) => (
          <Link key={competition.id} href={{ pathname: "/competition/[id]", params: { id: String(competition.id) } }} asChild>
            <Pressable style={styles.row}>
              <TeamBadge name={competition.name} logoUrl={competition.logo_url} size={32} />
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{competition.name}</Text>
                <Text style={styles.country}>{competition.country ?? "International"}</Text>
              </View>
            </Pressable>
          </Link>
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
    gap: 10,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    marginBottom: 10,
  },
  name: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "600",
  },
  country: {
    color: theme.textFaint,
    fontSize: 11,
    marginTop: 2,
  },
})

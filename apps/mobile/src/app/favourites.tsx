import { router } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native"

import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { TeamBadge } from "@/components/team-badge"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type { FavouritesOut } from "@/types/api"

export default function FavouritesScreen() {
  const [favourites, setFavourites] = useState<FavouritesOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setFavourites(await api.getFavourites())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to load favourites.")
    }
  }, [])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (error) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error} onRetry={load} />
      </View>
    )
  }

  if (!favourites) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading favourites…" />
      </View>
    )
  }

  async function unfollowTeam(teamId: number) {
    setFavourites((prev) =>
      prev ? { ...prev, teams: prev.teams.filter((f) => f.team.id !== teamId) } : prev,
    )
    await api.unfollowTeam(teamId).catch(() => {})
  }

  async function unfollowCompetition(competitionId: number) {
    setFavourites((prev) =>
      prev
        ? { ...prev, competitions: prev.competitions.filter((f) => f.competition.id !== competitionId) }
        : prev,
    )
    await api.unfollowCompetition(competitionId).catch(() => {})
  }

  async function unfollowMatch(matchId: number) {
    setFavourites((prev) =>
      prev ? { ...prev, matches: prev.matches.filter((f) => f.match.id !== matchId) } : prev,
    )
    await api.unfollowMatch(matchId).catch(() => {})
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>My Teams</Text>
        {favourites.teams.length === 0 ? (
          <EmptyState message="You're not following any teams yet." />
        ) : (
          favourites.teams.map((f) => (
            <Pressable
              key={f.id}
              style={styles.row}
              onPress={() => router.push({ pathname: "/team/[id]", params: { id: String(f.team.id) } })}
            >
              <TeamBadge name={f.team.name} shortName={f.team.short_name} logoUrl={f.team.logo_url} size={28} />
              <Text style={styles.rowText}>{f.team.name}</Text>
              <Pressable onPress={() => unfollowTeam(f.team.id)}>
                <Text style={styles.unfollow}>Unfollow</Text>
              </Pressable>
            </Pressable>
          ))
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>My Competitions</Text>
        {favourites.competitions.length === 0 ? (
          <EmptyState message="You're not following any competitions yet." />
        ) : (
          favourites.competitions.map((f) => (
            <Pressable
              key={f.id}
              style={styles.row}
              onPress={() =>
                router.push({ pathname: "/competition/[id]", params: { id: String(f.competition.id) } })
              }
            >
              <Text style={styles.rowText}>{f.competition.name}</Text>
              <Pressable onPress={() => unfollowCompetition(f.competition.id)}>
                <Text style={styles.unfollow}>Unfollow</Text>
              </Pressable>
            </Pressable>
          ))
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>My Matches</Text>
        {favourites.matches.length === 0 ? (
          <EmptyState message="You're not following any matches yet." />
        ) : (
          favourites.matches.map((f) => (
            <Pressable
              key={f.id}
              style={styles.row}
              onPress={() => router.push({ pathname: "/match/[id]", params: { id: String(f.match.id) } })}
            >
              <Text style={styles.rowText}>
                {f.match.home_team.name} vs {f.match.away_team.name}
              </Text>
              <Pressable onPress={() => unfollowMatch(f.match.id)}>
                <Text style={styles.unfollow}>Unfollow</Text>
              </Pressable>
            </Pressable>
          ))
        )}
      </View>
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
    gap: 12,
  },
  card: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 12,
    gap: 8,
  },
  sectionTitle: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 4,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
  },
  rowText: {
    flex: 1,
    color: theme.text,
    fontSize: 14,
  },
  unfollow: {
    color: theme.textFaint,
    fontSize: 12,
  },
})

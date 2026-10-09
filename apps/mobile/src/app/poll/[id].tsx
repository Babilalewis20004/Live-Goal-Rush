import { Link, useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { ScrollView, StyleSheet, View } from "react-native"

import { PollCard } from "@/components/community/poll-card"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { ApiError, api } from "@/lib/api"
import { theme } from "@/theme"
import type { PollOut } from "@/types/api"

export default function PollScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [poll, setPoll] = useState<PollOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setPoll(await api.getPoll(Number(id)))
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "This poll isn't available." : "Unable to load this poll.")
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (loading) return <View style={styles.screen}><LoadingState label="Loading poll…" /></View>
  if (error || !poll) return <View style={styles.screen}><ErrorState message={error ?? "Unable to load this poll."} onRetry={load} /></View>

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <PollCard poll={poll} />
      {poll.match_id ? (
        <Link href={{ pathname: "/match/[id]", params: { id: String(poll.match_id) } }} style={styles.link}>
          Go to the match →
        </Link>
      ) : null}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, gap: 16 },
  link: { color: theme.emerald, fontSize: 14 },
})

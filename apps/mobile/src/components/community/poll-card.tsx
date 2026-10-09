import { Link } from "expo-router"
import { useEffect, useState } from "react"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { leadingOption, pollClosing } from "@/lib/community"
import { theme } from "@/theme"
import type { PollOut } from "@/types/api"

/** One poll. Results are always visible as numbers and words (the bar is decoration).
 * Voting needs an account, is one vote per person, and can't be changed. */
export function PollCard({ poll: initial }: { poll: PollOut }) {
  const { user } = useAuth()
  const [poll, setPoll] = useState(initial)
  const [choice, setChoice] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!user) return
    let cancelled = false
    const handle = setTimeout(async () => {
      try {
        const mine = await api.getPoll(initial.id)
        if (!cancelled) setPoll(mine)
      } catch {
        // keep what we have
      }
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [user, initial.id])

  const open = poll.status === "open"
  const showResults = !open || poll.my_vote !== null
  const leader = leadingOption(poll)
  const closing = pollClosing(poll)

  async function vote() {
    if (choice === null || busy) return
    setBusy(true)
    setError(null)
    try {
      setPoll(await api.votePoll(poll.id, choice))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        try {
          setPoll(await api.getPoll(poll.id))
        } catch {
          // ignore
        }
      }
      setError(e instanceof ApiError ? e.message : "Couldn't record your vote.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <View style={styles.card} accessibilityLabel={`Poll: ${poll.question}`}>
      <Text accessibilityRole="header" style={styles.question}>
        {poll.question}
      </Text>
      <Text style={styles.meta}>
        {poll.total_votes} {poll.total_votes === 1 ? "vote" : "votes"}
        {closing ? ` · ${closing}` : ""}
      </Text>

      {showResults ? (
        <View style={{ marginTop: 10, gap: 10 }}>
          {poll.options.map((o) => {
            const mine = poll.my_vote === o.id
            const won = poll.winner_option_id === o.id
            return (
              <View key={o.id} accessible accessibilityLabel={`${o.label}: ${o.percent} percent, ${o.votes} votes${mine ? ", your vote" : ""}${won ? ", winner" : ""}`}>
                <View style={styles.resultRow}>
                  <Text style={styles.optionText}>
                    {o.label}
                    {mine ? "  · your vote" : ""}
                    {won ? "  · winner" : ""}
                  </Text>
                  <Text style={styles.percent}>
                    {o.percent}% <Text style={styles.meta}>({o.votes})</Text>
                  </Text>
                </View>
                <View style={styles.track}>
                  <View style={[styles.bar, { width: `${o.percent}%`, backgroundColor: mine ? theme.emerald : "rgba(255,255,255,0.4)" }]} />
                </View>
              </View>
            )
          })}
          {leader && poll.total_votes > 0 ? <Text style={styles.meta}>{open ? "Leading" : "Result"}: {leader}</Text> : null}
        </View>
      ) : (
        <View accessibilityRole="radiogroup" style={{ marginTop: 10, gap: 8 }}>
          {poll.options.map((o) => {
            const selected = choice === o.id
            return (
              <Pressable
                key={o.id}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected, disabled: !user }}
                accessibilityLabel={o.label}
                disabled={!user || busy}
                onPress={() => setChoice(o.id)}
                style={[styles.option, selected && styles.optionSelected]}
              >
                <View style={[styles.radio, selected && styles.radioOn]} />
                <Text style={styles.optionText}>{o.label}</Text>
              </Pressable>
            )
          })}
        </View>
      )}

      {open && poll.my_vote === null ? (
        user ? (
          <Pressable
            accessibilityRole="button"
            disabled={choice === null || busy}
            onPress={() => void vote()}
            style={[styles.vote, (choice === null || busy) && { opacity: 0.5 }]}
          >
            <Text style={styles.voteText}>{busy ? "Voting…" : "Vote"}</Text>
          </Pressable>
        ) : (
          <Text style={[styles.meta, { marginTop: 10 }]}>
            <Link href="/login" style={styles.link}>
              Sign in
            </Link>{" "}
            to vote.
          </Text>
        )
      ) : null}
      {error ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      ) : null}
    </View>
  )
}

/** Polls attached to a match or article (nothing rendered when there are none). */
export function PollsFor({ matchId, articleId }: { matchId?: number; articleId?: number }) {
  const [polls, setPolls] = useState<PollOut[]>([])
  useEffect(() => {
    let cancelled = false
    const handle = setTimeout(async () => {
      try {
        const found = await api.getPolls({ matchId, articleId, limit: 5 })
        if (!cancelled) setPolls(found)
      } catch {
        // additive
      }
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [matchId, articleId])
  if (polls.length === 0) return null
  return (
    <View style={{ gap: 12 }}>
      {polls.map((p) => (
        <PollCard key={p.id} poll={p} />
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  card: { padding: 14, borderRadius: 16, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card },
  question: { color: theme.text, fontSize: 15, fontWeight: "700" },
  meta: { color: theme.textFaint, fontSize: 11, marginTop: 2 },
  resultRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: 12 },
  optionText: { color: theme.text, fontSize: 14, flexShrink: 1 },
  percent: { color: theme.textMuted, fontSize: 13, fontWeight: "600" },
  track: { height: 6, borderRadius: 3, backgroundColor: "rgba(255,255,255,0.08)", marginTop: 4, overflow: "hidden" },
  bar: { height: 6, borderRadius: 3 },
  option: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 12, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border },
  optionSelected: { borderColor: theme.emerald, backgroundColor: "rgba(52,211,153,0.1)" },
  radio: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: theme.textFaint },
  radioOn: { borderColor: theme.emerald, backgroundColor: theme.emerald },
  vote: { marginTop: 12, minHeight: 44, borderRadius: 12, backgroundColor: theme.emerald, alignItems: "center", justifyContent: "center" },
  voteText: { color: theme.background, fontWeight: "700", fontSize: 14 },
  link: { color: theme.emerald, textDecorationLine: "underline" },
  error: { color: "#fca5a5", fontSize: 12, marginTop: 8 },
})

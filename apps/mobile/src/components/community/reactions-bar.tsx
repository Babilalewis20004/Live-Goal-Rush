import { Link } from "expo-router"
import { useEffect, useState } from "react"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { EMPTY_REACTIONS, REACTIONS, applyReaction } from "@/lib/community"
import { theme } from "@/theme"
import type { CommentTargetType, ReactionKind, ReactionSummary } from "@/types/api"

/** 👍 🔥 😮 ⚽ for an article or match. Counts are public; reacting needs an account.
 * One reaction per person: tap another to replace yours, tap yours to remove it.
 * Responds instantly and is corrected by the server's answer. */
export function ReactionsBar({ targetType, targetId }: { targetType: CommentTargetType; targetId: number }) {
  const { user, loading } = useAuth()
  const [summary, setSummary] = useState<ReactionSummary>(EMPTY_REACTIONS)
  const [notice, setNotice] = useState<"sign-in" | string | null>(null)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    if (loading) return
    let cancelled = false
    const handle = setTimeout(async () => {
      try {
        const fresh = await api.getReactions(targetType, targetId)
        if (!cancelled) setSummary(fresh)
      } catch {
        // counts are decoration
      }
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [targetType, targetId, user?.id, loading])

  async function choose(kind: ReactionKind) {
    if (!user) return setNotice("sign-in")
    if (pending) return
    const before = summary
    setSummary(applyReaction(before, kind))
    setNotice(null)
    setPending(true)
    try {
      setSummary(before.mine === kind ? await api.unreact(targetType, targetId) : await api.react(targetType, targetId, kind))
    } catch (error) {
      setSummary(before)
      setNotice(error instanceof ApiError && error.status === 429 ? "Slow down a little." : "Couldn't save your reaction.")
    } finally {
      setPending(false)
    }
  }

  return (
    <View>
      <View accessibilityRole="toolbar" accessibilityLabel="Reactions" style={styles.row}>
        {REACTIONS.map(({ kind, emoji, label }) => {
          const count = summary.counts[kind] ?? 0
          const selected = summary.mine === kind
          return (
            <Pressable
              key={kind}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              accessibilityLabel={`${label}, ${count} ${count === 1 ? "reaction" : "reactions"}${selected ? ", your reaction" : ""}`}
              onPress={() => void choose(kind)}
              style={[styles.chip, selected && styles.chipSelected]}
            >
              <Text style={styles.emoji}>{emoji}</Text>
              <Text style={styles.count}>{count}</Text>
            </Pressable>
          )
        })}
      </View>
      {notice === "sign-in" ? (
        <Text style={styles.notice} accessibilityLiveRegion="polite">
          <Link href="/login" style={styles.link}>
            Sign in
          </Link>{" "}
          to react.
        </Text>
      ) : notice ? (
        <Text style={styles.notice} accessibilityLiveRegion="polite">
          {notice}
        </Text>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    minHeight: 44,
    paddingHorizontal: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  chipSelected: { borderColor: theme.emerald, backgroundColor: "rgba(52,211,153,0.15)" },
  emoji: { fontSize: 16 },
  count: { color: theme.text, fontSize: 13, fontWeight: "600" },
  notice: { color: theme.textMuted, fontSize: 12, marginTop: 6 },
  link: { color: theme.emerald, textDecorationLine: "underline" },
})

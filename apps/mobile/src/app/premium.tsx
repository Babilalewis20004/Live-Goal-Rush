import { router } from "expo-router"
import { useEffect, useRef, useState } from "react"
import { Alert, Linking, Pressable, ScrollView, StyleSheet, Text, View } from "react-native"

import { useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { formatPrice, subscriptionStatusText } from "@/lib/analytics"
import { SITE_URL } from "@/lib/site"
import { theme } from "@/theme"

const FREE = [
  "Livescores and real-time match updates",
  "The full match centre, teams, players and competitions",
  "News, search, favourites and notifications",
  "Comments, reactions and polls",
  "Last-5 form, head-to-head and basic team analytics",
  "The headline match estimate",
]
const PREMIUM = [
  "Advanced team analytics: shots, possession, passing, defence, discipline, xG where supplied",
  "Last 10 / 20 / 38 match windows and full head-to-head history",
  "Full team-vs-team match comparison",
  "Detailed estimate breakdown",
  "Advanced player analytics: per-90 numbers and match-by-match history",
  "An ad-free experience",
]

/** Premium status and management. Subscribing happens on the website: payments are taken on the
 * payment provider's hosted page (we never see card details), and app-store rules for in-app
 * subscriptions are a separate decision -- see docs/architecture/monetisation.md. Cancelling is here. */
export default function PremiumScreen() {
  const { user } = useAuth()
  const plans = useAsync(() => api.getPlans(), "plans")
  const sub = useAsync(() => api.getSubscription(), `subscription:${user?.id ?? "anon"}`, 0, !!user)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const current = sub.data
  const isMounted = useRef(true)
  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
    }
  }, [])

  const hasPlan = !!current && ["active", "past_due", "cancelled"].includes(current.status) && current.entitlements.length > 0

  function confirmCancel() {
    Alert.alert("Cancel Premium?", "You keep Premium until the end of the period you've paid for.", [
      { text: "Keep Premium", style: "cancel" },
      {
        text: "Cancel subscription",
        style: "destructive",
        onPress: async () => {
          setBusy(true)
          setError(null)
          try {
            await api.cancelSubscription()
            sub.reload()
          } catch (e) {
            if (isMounted.current) setError(e instanceof ApiError ? e.message : "Couldn't cancel.")
          } finally {
            if (isMounted.current) setBusy(false)
          }
        },
      },
    ])
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text accessibilityRole="header" style={styles.h1}>LivePitch Premium</Text>
      <Text style={styles.muted}>Deeper analysis for people who like the numbers. The core football experience stays free.</Text>

      {user && current ? (
        <View style={styles.card}>
          <Text accessibilityRole="header" style={styles.h2}>Your plan</Text>
          <Text style={styles.muted}>{subscriptionStatusText(current.status, current.cancel_at_period_end, current.current_period_end)}</Text>
          {hasPlan && current.status !== "cancelled" ? (
            <Pressable accessibilityRole="button" accessibilityLabel="Cancel subscription" onPress={confirmCancel} disabled={busy} style={styles.ghost}>
              <Text style={styles.ghostText}>{busy ? "Cancelling…" : "Cancel subscription"}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      <View style={styles.card}>
        <Text accessibilityRole="header" style={styles.h2}>Free</Text>
        {FREE.map((f) => <Text key={f} style={styles.item}>✓ {f}</Text>)}
      </View>

      <View style={[styles.card, { borderColor: "rgba(52,211,153,0.3)" }]}>
        <Text accessibilityRole="header" style={styles.h2}>Premium</Text>
        {PREMIUM.map((f) => <Text key={f} style={styles.item}>★ {f}</Text>)}
        {plans.data?.map((p) => (
          <View key={p.code} style={styles.plan} accessible accessibilityLabel={`${p.name}, ${formatPrice(p)}`}>
            <Text style={styles.planName}>{p.name}</Text>
            <Text style={styles.muted}>{formatPrice(p)}</Text>
          </View>
        ))}
        {!user ? (
          <Pressable accessibilityRole="button" onPress={() => router.push("/login")} style={styles.cta}>
            <Text style={styles.ctaText}>Sign in to subscribe</Text>
          </Pressable>
        ) : !hasPlan ? (
          <Pressable accessibilityRole="button" accessibilityLabel="Subscribe on the website" onPress={() => void Linking.openURL(`${SITE_URL}/premium`)} style={styles.cta}>
            <Text style={styles.ctaText}>Subscribe on the website</Text>
          </Pressable>
        ) : null}
        {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      </View>

      <Text style={styles.fine}>
        Payments are handled by our payment provider on its own page; we never see or store your card details. Match estimates are statistical and not betting advice.
      </Text>
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, paddingBottom: 48, gap: 12 },
  h1: { color: theme.text, fontSize: 22, fontWeight: "700" },
  h2: { color: theme.text, fontSize: 14, fontWeight: "700" },
  muted: { color: theme.textMuted, fontSize: 13, lineHeight: 19 },
  card: { borderWidth: 1, borderColor: theme.border, backgroundColor: theme.card, borderRadius: 16, padding: 16, gap: 6 },
  item: { color: "rgba(255,255,255,0.78)", fontSize: 13, lineHeight: 19 },
  plan: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.border },
  planName: { color: theme.text, fontSize: 13, fontWeight: "600" },
  cta: { minHeight: 44, borderRadius: 12, backgroundColor: theme.emerald, alignItems: "center", justifyContent: "center", marginTop: 8 },
  ctaText: { color: "#000", fontWeight: "700" },
  ghost: { minHeight: 44, alignItems: "flex-start", justifyContent: "center" },
  ghostText: { color: theme.textMuted, textDecorationLine: "underline" },
  error: { color: "#fca5a5", fontSize: 13 },
  fine: { color: theme.textMuted, fontSize: 11, lineHeight: 16 },
})

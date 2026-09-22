import { useCallback, useEffect, useState } from "react"
import { ScrollView, StyleSheet, Switch, Text, View } from "react-native"

import { LoadingState } from "@/components/loading-state"
import { api } from "@/lib/api"
import { registerForPushNotificationsAsync } from "@/lib/push-notifications"
import { theme } from "@/theme"
import type { NotificationPreferenceOut, RealtimeEventType } from "@/types/api"

const DEFAULT_ON_EVENT_TYPES: { type: RealtimeEventType; label: string }[] = [
  { type: "MATCH_STARTED", label: "Kick-off" },
  { type: "GOAL", label: "Goals" },
  { type: "CARD", label: "Cards" },
  { type: "HALF_TIME", label: "Half-time" },
  { type: "MATCH_FINISHED", label: "Full-time" },
]

export default function NotificationSettingsScreen() {
  const [preferences, setPreferences] = useState<NotificationPreferenceOut[] | null>(null)

  const load = useCallback(async () => {
    setPreferences(await api.getNotificationPreferences().catch(() => []))
  }, [])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (!preferences) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading…" />
      </View>
    )
  }

  function effectiveEnabled(eventType: RealtimeEventType): boolean {
    const pref = preferences!.find((p) => p.scope_type === "global" && p.event_type === eventType)
    return pref ? pref.enabled : true
  }

  async function toggle(eventType: RealtimeEventType) {
    const next = !effectiveEnabled(eventType)
    const updated = await api.updateNotificationPreference("global", null, eventType, next).catch(() => null)
    if (!updated) return
    setPreferences((prev) => [
      ...(prev ?? []).filter((p) => !(p.scope_type === "global" && p.event_type === eventType)),
      updated,
    ])
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Push notifications</Text>
        <Text style={styles.subtitle}>Re-request permission and re-register this device.</Text>
        <Text style={styles.link} onPress={() => void registerForPushNotificationsAsync()}>
          Enable push notifications
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>What you get notified about</Text>
        <Text style={styles.subtitle}>
          Applies to every team, competition and match you follow. All on by default.
        </Text>
        {DEFAULT_ON_EVENT_TYPES.map(({ type, label }) => (
          <View key={type} style={styles.row}>
            <Text style={styles.rowText}>{label}</Text>
            <Switch
              value={effectiveEnabled(type)}
              onValueChange={() => void toggle(type)}
              trackColor={{ true: theme.emerald }}
            />
          </View>
        ))}
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
    padding: 16,
    gap: 8,
  },
  sectionTitle: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
  },
  subtitle: {
    color: theme.textFaint,
    fontSize: 12,
  },
  link: {
    color: theme.emerald,
    fontSize: 13,
    fontWeight: "600",
    marginTop: 4,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 4,
  },
  rowText: {
    color: theme.text,
    fontSize: 14,
  },
})

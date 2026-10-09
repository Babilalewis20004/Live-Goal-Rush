import { useCallback, useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native"

import { ContentNotificationSettings } from "@/components/content-notification-settings"
import { LoadingState } from "@/components/loading-state"
import { OverrideControl } from "@/components/override-control"
import { api } from "@/lib/api"
import {
  NOTIFIABLE_EVENTS,
  describeOverride,
  globallyMuted,
  overrideCount,
  overrideState,
  withOverride,
  type FavouriteScope,
  type OverrideState,
} from "@/lib/notification-overrides"
import { registerForPushNotificationsAsync } from "@/lib/push-notifications"
import { theme } from "@/theme"
import type { FavouritesOut, NotificationPreferenceOut, RealtimeEventType } from "@/types/api"

interface FavouriteItem {
  scope: FavouriteScope
  id: number
  title: string
}

function favouriteGroups(favourites: FavouritesOut | null): { heading: string; items: FavouriteItem[] }[] {
  if (!favourites) return []
  return [
    {
      heading: "Teams",
      items: favourites.teams.map((f) => ({ scope: "team" as const, id: f.team.id, title: f.team.name })),
    },
    {
      heading: "Competitions",
      items: favourites.competitions.map((f) => ({
        scope: "competition" as const,
        id: f.competition.id,
        title: f.competition.name,
      })),
    },
    {
      heading: "Matches",
      items: favourites.matches.map((f) => ({
        scope: "match" as const,
        id: f.match.id,
        title: `${f.match.home_team.name} v ${f.match.away_team.name}`,
      })),
    },
  ].filter((g) => g.items.length > 0)
}

export default function NotificationSettingsScreen() {
  const [preferences, setPreferences] = useState<NotificationPreferenceOut[] | null>(null)
  const [favourites, setFavourites] = useState<FavouritesOut | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const [prefs, favs] = await Promise.all([
      api.getNotificationPreferences().catch(() => []),
      api.getFavourites().catch(() => null),
    ])
    setPreferences(prefs)
    setFavourites(favs)
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

  async function setOverride(item: FavouriteItem, event: RealtimeEventType, state: OverrideState) {
    setError(null)
    try {
      if (state === "default") {
        await api.resetNotificationPreference(item.scope, item.id, event)
        setPreferences((prev) => withOverride(prev ?? [], item.scope, item.id, event, "default"))
      } else {
        const updated = await api.updateNotificationPreference(item.scope, item.id, event, state === "on")
        setPreferences((prev) => withOverride(prev ?? [], item.scope, item.id, event, state, updated))
      }
    } catch {
      setError("Couldn't save that change. Please try again.")
    }
  }

  const groups = favouriteGroups(favourites)

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
          Applies to every team, competition and match you follow. All on by default. Turning an event off here
          silences it everywhere, whatever you set below.
        </Text>
        {NOTIFIABLE_EVENTS.map(({ type, label }) => (
          <View key={type} style={styles.row}>
            <Text style={styles.rowText}>{label}</Text>
            <Switch
              value={effectiveEnabled(type)}
              onValueChange={() => void toggle(type)}
              trackColor={{ true: theme.emerald }}
              accessibilityLabel={`${label} notifications`}
            />
          </View>
        ))}
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle} accessibilityRole="header">
          Per-favourite settings
        </Text>
        <Text style={styles.subtitle}>
          Fine-tune individual favourites. Default notifies as normal. You&apos;re notified if any favourite that
          covers a match allows the event, so to silence a match completely switch the event off for each favourite
          that covers it (or use the toggles above).
        </Text>
        {groups.length === 0 ? (
          <Text style={styles.subtitle}>Follow a team, competition or match and it will appear here.</Text>
        ) : (
          groups.map((group) => (
            <View key={group.heading} style={{ gap: 8, marginTop: 8 }}>
              <Text style={styles.groupTitle}>{group.heading}</Text>
              {group.items.map((item) => {
                const key = `${item.scope}-${item.id}`
                const open = expanded === key
                const custom = overrideCount(preferences, item.scope, item.id)
                return (
                  <View key={key} style={styles.favourite}>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityState={{ expanded: open }}
                      accessibilityLabel={`${item.title}, ${custom > 0 ? `${custom} custom settings` : "default settings"}`}
                      onPress={() => setExpanded(open ? null : key)}
                      style={styles.favouriteHeader}
                    >
                      <Text style={styles.rowText} numberOfLines={1}>
                        {item.title}
                      </Text>
                      <Text style={styles.badge}>{custom > 0 ? `${custom} custom` : "Default"}</Text>
                    </Pressable>
                    {open && (
                      <View style={styles.favouriteBody}>
                        {NOTIFIABLE_EVENTS.map(({ type, label }) => {
                          const state = overrideState(preferences, item.scope, item.id, type)
                          return (
                            <View key={type} style={{ gap: 4 }}>
                              <View style={styles.row}>
                                <Text style={styles.rowText}>{label}</Text>
                                <OverrideControl
                                  label={`${item.title} ${label}`}
                                  state={state}
                                  onChange={(next) => void setOverride(item, type, next)}
                                />
                              </View>
                              <Text style={styles.hint}>{describeOverride(state, globallyMuted(preferences, type))}</Text>
                            </View>
                          )
                        })}
                      </View>
                    )}
                  </View>
                )
              })}
            </View>
          ))
        )}
        {error && (
          <Text style={styles.error} accessibilityRole="alert">
            {error}
          </Text>
        )}
      </View>

      <ContentNotificationSettings />
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, gap: 12, paddingBottom: 48 },
  card: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
    gap: 8,
  },
  sectionTitle: { color: theme.text, fontSize: 14, fontWeight: "700" },
  subtitle: { color: theme.textFaint, fontSize: 12 },
  link: { color: theme.emerald, fontSize: 13, fontWeight: "600", marginTop: 4 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 4, gap: 8 },
  rowText: { color: theme.text, fontSize: 14, flexShrink: 1 },
  groupTitle: { color: theme.textFaint, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  favourite: { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border },
  favouriteHeader: {
    minHeight: 48,
    paddingHorizontal: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  favouriteBody: { paddingHorizontal: 12, paddingBottom: 12, gap: 10, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.border },
  badge: { color: theme.textFaint, fontSize: 11 },
  hint: { color: theme.textFaint, fontSize: 11 },
  error: { color: theme.red, fontSize: 12, marginTop: 6 },
})

import { useEffect, useState } from "react"
import { StyleSheet, Switch, Text, View } from "react-native"

import { api, ApiError } from "@/lib/api"
import { CONTENT_KINDS } from "@/lib/news"
import { theme } from "@/theme"
import type { ContentNotificationKind, ContentPreferenceOut } from "@/types/api"

/** Which kinds of article may be pushed to this user. Everything is off until
 * switched on; article pushes are capped per day and go to the same devices as
 * match notifications. Renders nothing if the preferences can't be loaded. */
export function ContentNotificationSettings() {
  const [prefs, setPrefs] = useState<Record<string, boolean> | null>(null)
  const [pending, setPending] = useState<ContentNotificationKind | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const handle = setTimeout(async () => {
      try {
        const loaded: ContentPreferenceOut[] = await api.getContentPreferences()
        if (!cancelled) setPrefs(Object.fromEntries(loaded.map((p) => [p.kind, p.enabled])))
      } catch {
        // additive section: if it can't load, the rest of the screen is unaffected
      }
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [])

  if (!prefs) return null

  async function toggle(kind: ContentNotificationKind) {
    if (pending || !prefs) return
    const next = !prefs[kind]
    setPending(kind)
    setError(null)
    setPrefs({ ...prefs, [kind]: next })
    try {
      await api.setContentPreference(kind, next)
    } catch (e) {
      setPrefs((current) => (current ? { ...current, [kind]: !next } : current))
      setError(e instanceof ApiError ? e.message : "Couldn't save that. Try again.")
    } finally {
      setPending(null)
    }
  }

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.title}>
        News notifications
      </Text>
      <Text style={styles.subtitle}>
        Off by default. We never notify you about every article — at most a few a day, only for what you switch on and follow.
      </Text>
      {CONTENT_KINDS.map(({ kind, label, hint }) => (
        <View key={kind} style={styles.row}>
          <View style={{ flex: 1 }}>
            <Text style={styles.rowText}>{label}</Text>
            <Text style={styles.hint}>{hint}</Text>
          </View>
          <Switch
            accessibilityLabel={label}
            value={!!prefs[kind]}
            disabled={pending === kind}
            onValueChange={() => void toggle(kind)}
            trackColor={{ true: theme.emerald }}
          />
        </View>
      ))}
      {error ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
    gap: 10,
  },
  title: { color: theme.text, fontSize: 14, fontWeight: "700" },
  subtitle: { color: theme.textFaint, fontSize: 12, lineHeight: 17 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, minHeight: 48 },
  rowText: { color: theme.text, fontSize: 14 },
  hint: { color: theme.textFaint, fontSize: 11, marginTop: 1 },
  error: { color: "#fca5a5", fontSize: 12 },
})

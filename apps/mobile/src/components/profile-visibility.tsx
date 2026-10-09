import { router } from "expo-router"
import { useEffect, useState } from "react"
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from "react-native"

import { ApiError, api } from "@/lib/api"
import { theme } from "@/theme"
import type { MyProfileOut } from "@/types/api"

/** Public-profile switch, bio and badges. The profile is private until switched on;
 * what becomes visible is listed here. Renders nothing if it can't be loaded. */
export function ProfileVisibility() {
  const [profile, setProfile] = useState<MyProfileOut | null>(null)
  const [bio, setBio] = useState("")
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    const handle = setTimeout(async () => {
      try {
        const mine = await api.getMyProfile()
        if (!cancelled) {
          setProfile(mine)
          setBio(mine.bio ?? "")
        }
      } catch {
        // additive section
      }
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [])

  if (!profile) return null

  async function save(update: { profile_public?: boolean; bio?: string | null }, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      const next = await api.updateMyProfile(update)
      setProfile(next)
      setBio(next.bio ?? "")
      setMessage({ kind: "ok", text: success })
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't save that." })
    } finally {
      setBusy(false)
    }
  }

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.title}>
        Public profile
      </Text>
      <Text style={styles.sub}>
        Off by default. When on, anyone can see your display name, bio, badges, the teams and competitions you follow and your recent public comments — never your email.
      </Text>
      <View style={styles.row}>
        <Text style={styles.label}>Make my profile public</Text>
        <Switch
          accessibilityLabel="Make my profile public"
          value={profile.profile_public}
          disabled={busy}
          onValueChange={(v) => void save({ profile_public: v }, v ? "Your profile is public." : "Your profile is private.")}
          trackColor={{ true: theme.emerald }}
        />
      </View>
      <TextInput accessibilityLabel="Bio" placeholder="A line about you (optional)" placeholderTextColor={theme.textFaint} value={bio} onChangeText={setBio} maxLength={280} multiline style={styles.input} />
      <Pressable accessibilityRole="button" disabled={busy || bio === (profile.bio ?? "")} onPress={() => void save({ bio }, "Bio saved.")} style={[styles.button, (busy || bio === (profile.bio ?? "")) && { opacity: 0.5 }]}>
        <Text style={styles.buttonText}>Save bio</Text>
      </Pressable>
      {profile.badges.length > 0 ? (
        <View style={styles.badges}>
          {profile.badges.map((b) => (
            <View key={b.key} style={styles.badge} accessible accessibilityLabel={`${b.label}: ${b.description}`}>
              <Text style={styles.badgeText}>{b.label}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {profile.profile_public ? (
        <Pressable accessibilityRole="link" onPress={() => router.push({ pathname: "/u/[id]", params: { id: String(profile.id) } })}>
          <Text style={styles.link}>View your public profile →</Text>
        </Pressable>
      ) : null}
      {message ? (
        <Text accessibilityRole={message.kind === "error" ? "alert" : undefined} style={message.kind === "error" ? styles.error : styles.success}>
          {message.text}
        </Text>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  card: { borderRadius: 16, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card, padding: 16, gap: 10 },
  title: { color: theme.text, fontSize: 14, fontWeight: "700" },
  sub: { color: theme.textFaint, fontSize: 12, lineHeight: 17 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 },
  label: { color: theme.text, fontSize: 14 },
  input: { minHeight: 64, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, color: theme.text, paddingHorizontal: 12, paddingVertical: 8, fontSize: 14, textAlignVertical: "top" },
  button: { minHeight: 44, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, alignItems: "center", justifyContent: "center" },
  buttonText: { color: theme.text, fontWeight: "600" },
  badges: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  badge: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border },
  badgeText: { color: theme.textMuted, fontSize: 12 },
  link: { color: theme.emerald, fontSize: 13 },
  error: { color: "#fca5a5", fontSize: 12 },
  success: { color: theme.emerald, fontSize: 12 },
})

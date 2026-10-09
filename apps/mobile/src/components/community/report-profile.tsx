import { router } from "expo-router"
import { useState } from "react"
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native"

import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { theme } from "@/theme"

/** Report someone's public profile (bio / name). Needs an account, one report each; a moderator reviews it. */
export function ReportProfile({ userId }: { userId: number }) {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user?.id === userId) return null
  if (!user) {
    return (
      <Pressable accessibilityRole="button" accessibilityLabel="Sign in to report this profile" onPress={() => router.push("/login")} hitSlop={8} style={styles.link}>
        <Text style={styles.linkText}>Sign in to report this profile</Text>
      </Pressable>
    )
  }
  if (done) return <Text accessibilityRole="alert" style={styles.thanks}>Thanks — a moderator will take a look.</Text>

  async function send() {
    setBusy(true)
    setError(null)
    try {
      await api.reportProfile(userId, reason)
      setDone(true)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't send the report.")
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <Pressable accessibilityRole="button" accessibilityLabel="Report this profile" onPress={() => setOpen(true)} hitSlop={8} style={styles.link}>
        <Text style={styles.linkText}>Report this profile</Text>
      </Pressable>
    )
  }
  return (
    <View style={{ gap: 8 }}>
      <TextInput
        accessibilityLabel="Why are you reporting this profile?"
        placeholder="Why are you reporting this profile? (optional)"
        placeholderTextColor={theme.textFaint}
        value={reason}
        onChangeText={setReason}
        maxLength={200}
        style={styles.input}
      />
      <View style={{ flexDirection: "row", gap: 12 }}>
        <Pressable accessibilityRole="button" accessibilityLabel="Send report" onPress={send} disabled={busy} style={styles.send}>
          <Text style={styles.sendText}>{busy ? "Sending…" : "Send report"}</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Cancel" onPress={() => setOpen(false)} hitSlop={8} style={styles.link}>
          <Text style={styles.linkText}>Cancel</Text>
        </Pressable>
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
  )
}

const styles = StyleSheet.create({
  link: { minHeight: 36, justifyContent: "center", alignSelf: "flex-start" },
  linkText: { color: theme.textMuted, fontSize: 12, textDecorationLine: "underline" },
  thanks: { color: theme.textMuted, fontSize: 12 },
  input: { minHeight: 44, borderWidth: 1, borderColor: theme.border, borderRadius: 10, paddingHorizontal: 12, color: theme.text },
  send: { minHeight: 40, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.12)", paddingHorizontal: 14, justifyContent: "center" },
  sendText: { color: theme.text, fontSize: 13 },
  error: { color: "#fca5a5", fontSize: 12 },
})

import { useState } from "react"
import { Pressable, Share, StyleSheet, Text, TextInput, View } from "react-native"

import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { theme } from "@/theme"

/** Download-my-data and delete-my-account (Phase 7 privacy), mirroring `apps/web/components/privacy-data.tsx`.
 * Both are enforced by the API: the password is checked server-side and the export holds only this person's data. */
export function PrivacyData() {
  const { logout } = useAuth()
  const [exporting, setExporting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [password, setPassword] = useState("")
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function handleExport() {
    setError(null)
    setMessage(null)
    setExporting(true)
    try {
      const data = await api.exportMyData()
      await Share.share({ title: "My LivePitch data", message: JSON.stringify(data, null, 2) })
      setMessage("Your data is ready to save or send.")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not export your data. Please try again.")
    } finally {
      setExporting(false)
    }
  }

  async function handleDelete() {
    setError(null)
    setDeleting(true)
    try {
      await api.deleteAccount(password)
      await logout().catch(() => undefined) // the session is already gone server-side; this clears the device
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete your account. Please try again.")
      setDeleting(false)
    }
  }

  return (
    <View style={styles.card}>
      <Text style={styles.sectionTitle}>Your data</Text>
      <Text style={styles.help}>
        Download a copy of what you have given us, or erase your account. Erasing removes your favourites, devices,
        reactions, votes and notification history, and anonymises your comments. Billing records are kept as the law
        requires.
      </Text>
      <Pressable accessibilityRole="button" style={styles.button} onPress={handleExport} disabled={exporting}>
        <Text style={styles.buttonText}>{exporting ? "Preparing…" : "Download my data"}</Text>
      </Pressable>

      {!confirming ? (
        <Pressable accessibilityRole="button" style={styles.dangerOutline} onPress={() => setConfirming(true)}>
          <Text style={styles.dangerText}>Delete my account…</Text>
        </Pressable>
      ) : (
        <View style={styles.dangerBox}>
          <Text style={styles.dangerHelp}>This cannot be undone. Any subscription is cancelled. Enter your password to confirm.</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            accessibilityLabel="Password to confirm account deletion"
            placeholder="Password"
            placeholderTextColor={theme.textFaint}
          />
          <View style={styles.row}>
            <Pressable
              accessibilityRole="button"
              style={[styles.half, styles.cancel]}
              onPress={() => {
                setConfirming(false)
                setPassword("")
                setError(null)
              }}
            >
              <Text style={styles.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              style={[styles.half, styles.danger, (!password || deleting) && styles.disabled]}
              onPress={handleDelete}
              disabled={!password || deleting}
            >
              <Text style={styles.dangerButtonText}>{deleting ? "Deleting…" : "Delete forever"}</Text>
            </Pressable>
          </View>
        </View>
      )}
      {error && <Text style={styles.error}>{error}</Text>}
      {message && <Text style={styles.success}>{message}</Text>}
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
  sectionTitle: { color: theme.text, fontSize: 14, fontWeight: "700" },
  help: { color: theme.textFaint, fontSize: 12, lineHeight: 17 },
  button: { backgroundColor: theme.emerald, borderRadius: 12, paddingVertical: 12, alignItems: "center" },
  buttonText: { color: theme.background, fontWeight: "700", fontSize: 14 },
  dangerOutline: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "rgba(248,113,113,0.4)",
    paddingVertical: 12,
    alignItems: "center",
  },
  dangerText: { color: theme.red, fontWeight: "600", fontSize: 14 },
  dangerBox: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "rgba(248,113,113,0.4)",
    padding: 12,
    gap: 10,
  },
  dangerHelp: { color: theme.red, fontSize: 12, lineHeight: 17 },
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: "rgba(255,255,255,0.03)",
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: theme.text,
    fontSize: 14,
  },
  row: { flexDirection: "row", gap: 8 },
  half: { flex: 1, borderRadius: 12, paddingVertical: 12, alignItems: "center" },
  cancel: { borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border },
  cancelText: { color: theme.textFaint, fontWeight: "600", fontSize: 14 },
  danger: { backgroundColor: "#ef4444" },
  dangerButtonText: { color: "#fff", fontWeight: "700", fontSize: 14 },
  disabled: { opacity: 0.5 },
  error: { color: theme.red, fontSize: 12 },
  success: { color: theme.emerald, fontSize: 12 },
})

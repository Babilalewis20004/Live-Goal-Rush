import { router } from "expo-router"
import { useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native"

import { LoadingState } from "@/components/loading-state"
import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { theme } from "@/theme"

export default function ProfileScreen() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading…" />
      </View>
    )
  }

  if (!user) {
    return (
      <View style={[styles.screen, styles.centered]}>
        <Text style={styles.title}>You&apos;re not logged in</Text>
        <Text style={styles.subtitle}>Log in to follow teams, competitions and matches.</Text>
        <Pressable style={styles.button} onPress={() => router.push("/login")}>
          <Text style={styles.buttonText}>Log in</Text>
        </Pressable>
        <Pressable style={styles.secondaryButton} onPress={() => router.push("/register")}>
          <Text style={styles.secondaryButtonText}>Create an account</Text>
        </Pressable>
      </View>
    )
  }

  return <LoggedInProfile />
}

function LoggedInProfile() {
  const { user, logout } = useAuth()
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleChangePassword() {
    setError(null)
    setMessage(null)
    setSubmitting(true)
    try {
      await api.changePassword(currentPassword, newPassword)
      setMessage("Password changed.")
      setCurrentPassword("")
      setNewPassword("")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.title}>{user!.display_name || user!.email}</Text>
        <Text style={styles.subtitle}>{user!.email}</Text>
      </View>

      <Pressable style={styles.linkCard} onPress={() => router.push("/favourites")}>
        <Text style={styles.linkCardText}>Manage favourite teams, competitions &amp; matches</Text>
      </Pressable>

      <Pressable style={styles.linkCard} onPress={() => router.push("/notification-settings")}>
        <Text style={styles.linkCardText}>Notification settings</Text>
      </Pressable>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Change password</Text>
        <TextInput
          style={styles.input}
          value={currentPassword}
          onChangeText={setCurrentPassword}
          secureTextEntry
          placeholder="Current password"
          placeholderTextColor={theme.textFaint}
        />
        <TextInput
          style={styles.input}
          value={newPassword}
          onChangeText={setNewPassword}
          secureTextEntry
          placeholder="New password"
          placeholderTextColor={theme.textFaint}
        />
        {error && <Text style={styles.error}>{error}</Text>}
        {message && <Text style={styles.success}>{message}</Text>}
        <Pressable style={styles.button} onPress={handleChangePassword} disabled={submitting}>
          <Text style={styles.buttonText}>{submitting ? "Saving…" : "Change password"}</Text>
        </Pressable>
      </View>

      <Pressable style={styles.secondaryButton} onPress={() => void logout()}>
        <Text style={styles.secondaryButtonText}>Log out</Text>
      </Pressable>
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: theme.background,
  },
  centered: {
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
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
    gap: 10,
  },
  linkCard: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
  },
  linkCardText: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "600",
  },
  title: {
    color: theme.text,
    fontSize: 17,
    fontWeight: "700",
  },
  subtitle: {
    color: theme.textFaint,
    fontSize: 13,
    textAlign: "center",
  },
  sectionTitle: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
  },
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
  error: {
    color: theme.red,
    fontSize: 12,
  },
  success: {
    color: theme.emerald,
    fontSize: 12,
  },
  button: {
    backgroundColor: theme.emerald,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
  },
  buttonText: {
    color: theme.background,
    fontWeight: "700",
    fontSize: 14,
  },
  secondaryButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryButtonText: {
    color: theme.textMuted,
    fontWeight: "600",
    fontSize: 14,
  },
})

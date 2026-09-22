import { Link, router } from "expo-router"
import { useState } from "react"
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native"

import { useAuth } from "@/hooks/use-auth"
import { ApiError } from "@/lib/api"
import { theme } from "@/theme"

export default function RegisterScreen() {
  const { register } = useAuth()
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [password, setPassword] = useState("")
  const [passwordConfirm, setPasswordConfirm] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit() {
    setError(null)
    if (password !== passwordConfirm) {
      setError("Passwords do not match.")
      return
    }
    setSubmitting(true)
    try {
      await register(email, password, displayName)
      router.back()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <View style={styles.screen}>
      <Text style={styles.label}>Email</Text>
      <TextInput
        style={styles.input}
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        placeholderTextColor={theme.textFaint}
      />

      <Text style={styles.label}>Display name (optional)</Text>
      <TextInput
        style={styles.input}
        value={displayName}
        onChangeText={setDisplayName}
        placeholderTextColor={theme.textFaint}
      />

      <Text style={styles.label}>Password</Text>
      <TextInput
        style={styles.input}
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        placeholderTextColor={theme.textFaint}
      />

      <Text style={styles.label}>Confirm password</Text>
      <TextInput
        style={styles.input}
        value={passwordConfirm}
        onChangeText={setPasswordConfirm}
        secureTextEntry
        placeholderTextColor={theme.textFaint}
      />

      {error && <Text style={styles.error}>{error}</Text>}

      <Pressable style={styles.button} onPress={handleSubmit} disabled={submitting}>
        <Text style={styles.buttonText}>{submitting ? "Creating account…" : "Create account"}</Text>
      </Pressable>

      <Link href="/login" style={styles.link}>
        Already have an account? Log in
      </Link>
    </View>
  )
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: theme.background,
    padding: 20,
    gap: 8,
  },
  label: {
    color: theme.textMuted,
    fontSize: 12,
    fontWeight: "600",
    marginTop: 8,
  },
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: theme.text,
    fontSize: 15,
  },
  error: {
    color: theme.red,
    fontSize: 12,
    marginTop: 4,
  },
  button: {
    marginTop: 16,
    backgroundColor: theme.emerald,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonText: {
    color: theme.background,
    fontWeight: "700",
    fontSize: 15,
  },
  link: {
    marginTop: 16,
    textAlign: "center",
    color: theme.textFaint,
    fontSize: 13,
  },
})

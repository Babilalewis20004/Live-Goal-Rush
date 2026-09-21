import { Pressable, StyleSheet, Text, View } from "react-native"
import { theme } from "@/theme"

export function ErrorState({
  message = "Unable to load data.",
  onRetry,
}: {
  message?: string
  onRetry?: () => void
}) {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>{message}</Text>
      {onRetry && (
        <Pressable style={styles.button} onPress={onRetry}>
          <Text style={styles.buttonText}>Try again</Text>
        </Pressable>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    paddingVertical: 48,
    paddingHorizontal: 24,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(239,68,68,0.3)",
    backgroundColor: "rgba(239,68,68,0.08)",
  },
  text: {
    color: theme.textMuted,
    fontSize: 13,
    textAlign: "center",
  },
  button: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 999,
  },
  buttonText: {
    color: theme.text,
    fontSize: 12,
    fontWeight: "600",
  },
})

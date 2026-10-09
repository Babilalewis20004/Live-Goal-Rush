import { Ionicons } from "@expo/vector-icons"
import { Pressable, Share, StyleSheet, Text } from "react-native"

import { publicUrl, type ShareableKind } from "@/lib/site"
import { theme } from "@/theme"

/** Opens the native share sheet with the canonical public URL of a page. The
 * link is built from the entity's id/slug alone -- nothing about the sharer
 * (account, session, filters) can end up in it. */
export function ShareButton({
  kind,
  id,
  title,
  label = "Share",
}: {
  kind: ShareableKind
  id: number | string
  title: string
  label?: string
}) {
  async function share() {
    const url = publicUrl(kind, id)
    try {
      // iOS shows `url` natively; Android only shows `message`, so include it there.
      await Share.share({ title, message: `${title}\n${url}`, url })
    } catch {
      // dismissed or unavailable: nothing to report
    }
  }

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${title}`}
      onPress={share}
      style={({ pressed }) => [styles.button, pressed && { opacity: 0.7 }]}
      hitSlop={6}
    >
      <Ionicons name="share-outline" size={16} color={theme.textMuted} />
      <Text style={styles.text}>{label}</Text>
    </Pressable>
  )
}

const styles = StyleSheet.create({
  button: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 40,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    alignSelf: "flex-start",
  },
  text: { color: theme.textMuted, fontSize: 12, fontWeight: "600" },
})

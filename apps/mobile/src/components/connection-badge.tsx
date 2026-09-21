import { StyleSheet, Text, View } from "react-native"
import type { ConnectionStatus } from "@/lib/realtime"
import { theme } from "@/theme"

const LABEL: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  closed: "Offline",
}

const DOT_COLOR: Record<ConnectionStatus, string> = {
  connecting: theme.amber,
  open: theme.emerald,
  reconnecting: theme.amber,
  closed: theme.red,
}

/** Surfaces the WebSocket connection state (spec §18/§19/§29) -- mirrors
 * apps/web/components/ui/connection-badge.tsx. */
export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <View style={styles.badge}>
      <View style={[styles.dot, { backgroundColor: DOT_COLOR[status] }]} />
      <Text style={styles.label}>{LABEL[status]}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: "flex-end",
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  label: {
    color: theme.textFaint,
    fontSize: 10,
    fontWeight: "600",
  },
})

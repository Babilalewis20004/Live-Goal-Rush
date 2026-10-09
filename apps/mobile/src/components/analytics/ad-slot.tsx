import { StyleSheet, Text, View } from "react-native"

import { useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { theme } from "@/theme"
import type { AdPlacementOut } from "@/types/api"

/** Reserves a labelled slot where an ad may go, if (and only if) the server says this viewer is eligible
 * at this placement. No ad network, tracking or identifier here. Renders nothing for Premium viewers,
 * during live matches, or when ads are off. */
export function AdSlot({ placement, live = false }: { placement: AdPlacementOut["placement"]; live?: boolean }) {
  const { user } = useAuth()
  const { data } = useAsync(() => api.getAdPlacements(live), `ads:${live}:${user?.id ?? "anon"}`)
  const eligible = data?.find((p) => p.placement === placement)?.eligible
  if (!eligible) return null
  return (
    <View accessible accessibilityLabel="Advertisement" style={styles.box}>
      <Text style={styles.text}>Advertisement</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  box: { borderWidth: 1, borderStyle: "dashed", borderColor: theme.border, borderRadius: 12, paddingVertical: 24, alignItems: "center" },
  text: { color: theme.textMuted, fontSize: 10, textTransform: "uppercase" },
})

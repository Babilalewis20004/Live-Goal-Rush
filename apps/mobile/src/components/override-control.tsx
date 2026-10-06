import { Pressable, StyleSheet, Text, View } from "react-native"

import { OVERRIDE_LABELS, type OverrideState } from "@/lib/notification-overrides"
import { theme } from "@/theme"

const STATES = Object.keys(OVERRIDE_LABELS) as OverrideState[]

/** A three-way Default / On / Off control, exposed as an accessible radio group. */
export function OverrideControl({
  label,
  state,
  onChange,
}: {
  label: string
  state: OverrideState
  onChange: (next: OverrideState) => void
}) {
  return (
    <View style={styles.segment} accessibilityRole="radiogroup" accessibilityLabel={label}>
      {STATES.map((s) => {
        const selected = s === state
        return (
          <Pressable
            key={s}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={`${label}: ${OVERRIDE_LABELS[s]}`}
            onPress={() => onChange(s)}
            style={[styles.option, selected && styles.optionSelected]}
            hitSlop={4}
          >
            <Text style={[styles.text, selected && styles.textSelected]}>{OVERRIDE_LABELS[s]}</Text>
          </Pressable>
        )
      })}
    </View>
  )
}

const styles = StyleSheet.create({
  segment: { flexDirection: "row", borderRadius: 10, backgroundColor: "rgba(255,255,255,0.07)", padding: 2 },
  option: { minHeight: 36, minWidth: 56, alignItems: "center", justifyContent: "center", borderRadius: 8, paddingHorizontal: 8 },
  optionSelected: { backgroundColor: "rgba(255,255,255,0.18)" },
  text: { color: theme.textMuted, fontSize: 12, fontWeight: "600" },
  textSelected: { color: theme.text },
})

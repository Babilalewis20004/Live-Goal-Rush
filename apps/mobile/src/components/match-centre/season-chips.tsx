import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native"

import { selectableSeasons } from "@/lib/seasons"
import { theme } from "@/theme"
import type { CompetitionSeasonsOut } from "@/types/api"

/** Season picker as a row of chips. Stored seasons first; when the provider
 * supports history a few earlier ones are offered ("load" = fetched on demand,
 * the table appears shortly). `value === null` is the current season. */
export function SeasonChips({
  info,
  value,
  onChange,
}: {
  info: CompetitionSeasonsOut | null
  value: string | null
  onChange: (season: string | null) => void
}) {
  const options = selectableSeasons(info)
  if (options.length <= 1) return null
  const current = info?.current ?? null

  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={styles.label}>Season</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityRole="radiogroup" contentContainerStyle={styles.row}>
        {options.map((o) => {
          const selected = (value ?? current) === o.label
          return (
            <Pressable
              key={o.label}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected }}
              accessibilityLabel={`Season ${o.label}${o.label === current ? ", current" : o.stored ? "" : ", load from provider"}`}
              onPress={() => onChange(o.label === current ? null : o.label)}
              style={[styles.chip, selected && styles.chipSelected]}
              hitSlop={4}
            >
              <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                {o.label}
                {o.stored ? "" : " ↓"}
              </Text>
            </Pressable>
          )
        })}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  label: { color: theme.textFaint, fontSize: 11, fontWeight: "700", textTransform: "uppercase", marginBottom: 6 },
  row: { gap: 6 },
  chip: {
    minHeight: 40,
    paddingHorizontal: 14,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  chipSelected: { backgroundColor: "rgba(255,255,255,0.14)", borderColor: "rgba(255,255,255,0.3)" },
  chipText: { color: theme.textMuted, fontSize: 13, fontWeight: "600" },
  chipTextSelected: { color: theme.text },
})

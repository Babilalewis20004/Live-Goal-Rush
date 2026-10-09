import { useState } from "react"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { LockedNote, PremiumGate } from "@/components/analytics/premium-gate"
import { Card } from "@/components/match-centre/ui"
import { isPaymentRequired, useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { coverage, formatStat, timeAgo } from "@/lib/analytics"
import { theme } from "@/theme"
import type { Stat, TeamAnalyticsOut } from "@/types/api"

const LABELS: Record<string, { label: string; suffix?: string; digits?: number }> = {
  goals: { label: "Goals" },
  goals_per_match: { label: "Goals per match", digits: 2 },
  shots: { label: "Shots" },
  shots_per_match: { label: "Shots per match" },
  shots_on_target: { label: "Shots on target" },
  shot_conversion_pct: { label: "Shot conversion", suffix: "%" },
  expected_goals: { label: "Expected goals (xG)" },
  expected_goals_per_match: { label: "xG per match", digits: 2 },
  assists: { label: "Assists" },
  chances_created: { label: "Chances created" },
  possession_pct: { label: "Average possession", suffix: "%" },
  pass_accuracy_pct: { label: "Pass accuracy", suffix: "%" },
  passes: { label: "Passes" },
  goals_conceded: { label: "Goals conceded" },
  goals_conceded_per_match: { label: "Conceded per match", digits: 2 },
  clean_sheets: { label: "Clean sheets" },
  tackles: { label: "Tackles" },
  interceptions: { label: "Interceptions" },
  clearances: { label: "Clearances" },
  blocks: { label: "Blocks" },
  yellow_cards: { label: "Yellow cards" },
  red_cards: { label: "Red cards" },
  fouls: { label: "Fouls" },
}

function Section({ title, stats, matches }: { title: string; stats: Record<string, Stat>; matches: number }) {
  const entries = Object.entries(stats)
  if (entries.length === 0) return null
  return (
    <View style={{ marginTop: 12 }}>
      <Text style={styles.sub} accessibilityRole="header">{title}</Text>
      {entries.map(([key, stat]) => {
        const meta = LABELS[key] ?? { label: key.replaceAll("_", " ") }
        const partial = coverage(stat, matches)
        const value = formatStat(stat, { suffix: meta.suffix, digits: meta.digits })
        return (
          <View key={key} style={styles.row} accessible accessibilityLabel={`${meta.label}: ${stat.value === null ? "not provided by the data source" : value}${partial ? `, ${partial}` : ""}`}>
            <Text style={styles.label}>{meta.label}</Text>
            <Text style={styles.value}>
              {value}
              {partial ? <Text style={styles.fine}>  {partial}</Text> : null}
            </Text>
          </View>
        )
      })}
    </View>
  )
}

export function TeamAnalyticsView({ data, signedIn }: { data: TeamAnalyticsOut; signedIn: boolean }) {
  const r = data.record
  const updated = timeAgo(data.generated_at)
  return (
    <View>
      <Text style={styles.sub} accessibilityRole="header">
        Record · last {data.matches_considered} {data.scope === "overall" ? "" : `${data.scope} `}matches
      </Text>
      <Text style={styles.record}>
        {r.wins} won, {r.draws} drawn, {r.losses} lost · {r.points} points{r.points_per_match !== null ? ` (${r.points_per_match} per match)` : ""}
      </Text>
      <Section title="Attack" stats={data.attack} matches={data.matches_considered} />
      <Section title="Possession & passing" stats={data.possession} matches={data.matches_considered} />
      <Section title="Defence" stats={data.defence} matches={data.matches_considered} />
      <Section title="Discipline" stats={data.discipline} matches={data.matches_considered} />
      <LockedNote locked={data.locked} signedIn={signedIn} />
      {data.unavailable.length > 0 && <Text style={styles.fine}>Not tracked by this platform: {data.unavailable.map((u) => u.replaceAll("_", " ")).join(", ")}.</Text>}
      {data.limitations.map((l) => (
        <Text key={l} style={styles.warn}>{l}</Text>
      ))}
      <Text style={styles.fine}>Calculated from stored results and match statistics{updated ? ` · updated ${updated}` : ""}.</Text>
    </View>
  )
}

const SCOPES = ["overall", "home", "away"] as const
const WINDOWS = [5, 10, 20, 38] as const

function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityState={{ selected }} accessibilityLabel={label} onPress={onPress} hitSlop={4} style={[styles.chip, selected && styles.chipOn]}>
      <Text style={[styles.chipText, selected && { color: theme.text }]}>{label}</Text>
    </Pressable>
  )
}

/** Team analytics. Longer windows are Premium: the server answers 402 and we say why. */
export function TeamAnalytics({ teamId }: { teamId: number }) {
  const { user } = useAuth()
  const [scope, setScope] = useState<(typeof SCOPES)[number]>("overall")
  const [window, setWindow] = useState<(typeof WINDOWS)[number]>(10)
  const { data, error, loading } = useAsync(() => api.getTeamAnalytics(teamId, { scope, window }), `team-analytics:${teamId}:${scope}:${window}:${user?.id ?? "anon"}`)
  return (
    <Card>
      <View style={styles.chips}>
        {SCOPES.map((s) => (
          <Chip key={s} label={s[0].toUpperCase() + s.slice(1)} selected={scope === s} onPress={() => setScope(s)} />
        ))}
      </View>
      <View style={styles.chips}>
        {WINDOWS.map((w) => (
          <Chip key={w} label={`Last ${w}${w > 10 ? " 🔒" : ""}`} selected={window === w} onPress={() => setWindow(w)} />
        ))}
      </View>
      {loading && !data && <Text style={styles.fine}>Loading analytics…</Text>}
      {isPaymentRequired(error) ? (
        <View style={{ marginTop: 10 }}>
          <PremiumGate title="Longer history" items={["Last 20 and last 38 matches", "Extended form and head-to-head"]} signedIn={!!user} />
        </View>
      ) : error && !data ? (
        <Text style={styles.fine}>Analytics aren&apos;t available right now.</Text>
      ) : (
        data && <View style={{ marginTop: 8 }}><TeamAnalyticsView data={data} signedIn={!!user} /></View>
      )}
    </Card>
  )
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 6 },
  chip: { minHeight: 36, paddingHorizontal: 12, borderRadius: 999, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, justifyContent: "center" },
  chipOn: { borderColor: "rgba(52,211,153,0.6)", backgroundColor: "rgba(52,211,153,0.15)" },
  chipText: { color: theme.textMuted, fontSize: 12 },
  sub: { color: theme.textMuted, fontSize: 11, fontWeight: "700", textTransform: "uppercase", marginBottom: 4 },
  record: { color: "rgba(255,255,255,0.85)", fontSize: 13 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.border },
  label: { color: theme.textMuted, fontSize: 13 },
  value: { color: theme.text, fontSize: 13, fontWeight: "700" },
  fine: { color: theme.textMuted, fontSize: 10, lineHeight: 14, marginTop: 6 },
  warn: { color: "rgba(253,230,138,0.75)", fontSize: 11, marginTop: 6 },
})

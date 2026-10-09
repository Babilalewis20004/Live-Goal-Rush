import { StyleSheet, Text, View } from "react-native"

import { LockedNote } from "@/components/analytics/premium-gate"
import { Card, SectionTitle } from "@/components/match-centre/ui"
import { useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { formatNumber, formatStat } from "@/lib/analytics"
import { theme } from "@/theme"
import type { PlayerAnalyticsOut } from "@/types/api"

const TOTALS: [string, string][] = [
  ["minutes_played", "Minutes"], ["goals", "Goals"], ["assists", "Assists"], ["shots", "Shots"],
  ["shots_on_target", "On target"], ["key_passes", "Chances created"], ["tackles", "Tackles"], ["interceptions", "Interceptions"],
]
const PER90: [string, string][] = [
  ["goals", "Goals"], ["assists", "Assists"], ["shots", "Shots"], ["key_passes", "Chances created"], ["tackles", "Tackles"],
]

/** Goal involvements per match as small bars. The numbers are also in the accessibility label, so the bars are never the only carrier. */
function Trend({ values }: { values: number[] }) {
  const max = Math.max(1, ...values)
  return (
    <View style={styles.trend} accessible accessibilityLabel={`Goal involvements in the last ${values.length} matches, oldest to newest: ${values.join(", ")}`}>
      {values.map((v, i) => (
        <View key={i} style={{ width: 14, height: Math.max(4, (v / max) * 40), backgroundColor: "rgba(52,211,153,0.7)", borderRadius: 2 }} />
      ))}
    </View>
  )
}

export function PlayerAnalyticsView({ data, signedIn, showSeasons = true }: { data: PlayerAnalyticsOut; signedIn: boolean; showSeasons?: boolean }) {
  const full = data.tier === "full"
  return (
    <View style={{ gap: 12 }}>
      {showSeasons && data.seasons.length > 0 && (
        <View>
          <Text style={styles.sub} accessibilityRole="header">Season history</Text>
          {data.seasons.map((s) => (
            <View key={`${s.competition_id}-${s.season}`} style={styles.row} accessible accessibilityLabel={`${s.season}, ${s.competition_name}: ${formatNumber(s.appearances)} appearances, ${s.goals} goals, ${formatNumber(s.assists)} assists`}>
              <Text style={styles.label}>{s.season} · {s.competition_name}</Text>
              <Text style={styles.value}>{formatNumber(s.appearances)} / {s.goals} / {formatNumber(s.assists)}</Text>
            </View>
          ))}
          <Text style={styles.fine}>Appearances / goals / assists</Text>
        </View>
      )}
      {full && data.matches_with_statistics > 0 && (
        <>
          <View>
            <Text style={styles.sub} accessibilityRole="header">Last {data.matches_with_statistics} matches with statistics</Text>
            <View style={styles.grid}>
              {TOTALS.map(([key, label]) => (
                <View key={key} style={styles.cell} accessible accessibilityLabel={`${label}: ${formatStat(data.totals[key], { digits: 0 })}`}>
                  <Text style={styles.fine}>{label}</Text>
                  <Text style={styles.value}>{formatStat(data.totals[key], { digits: 0 })}</Text>
                </View>
              ))}
            </View>
          </View>
          <View>
            <Text style={styles.sub} accessibilityRole="header">Per 90 minutes</Text>
            <View style={styles.grid}>
              {PER90.map(([key, label]) => (
                <View key={key} style={styles.cell} accessible accessibilityLabel={`${label} per 90: ${formatStat(data.per_90[key], { digits: 2 })}`}>
                  <Text style={styles.fine}>{label}</Text>
                  <Text style={styles.value}>{formatStat(data.per_90[key], { digits: 2 })}</Text>
                </View>
              ))}
            </View>
          </View>
          {data.form_goal_involvements.length > 1 && (
            <View>
              <Text style={styles.sub} accessibilityRole="header">Goals + assists, match by match</Text>
              <Trend values={data.form_goal_involvements} />
            </View>
          )}
          <View>
            <Text style={styles.sub} accessibilityRole="header">Match by match</Text>
            {data.recent.map((m) => (
              <View key={m.match_id} style={styles.row} accessible accessibilityLabel={`Against ${m.opponent}: ${formatNumber(m.minutes)} minutes, ${formatNumber(m.goals)} goals, ${formatNumber(m.assists)} assists`}>
                <Text style={styles.label}>{m.opponent}</Text>
                <Text style={styles.value}>{formatNumber(m.minutes)}′ · {formatNumber(m.goals)}G {formatNumber(m.assists)}A</Text>
              </View>
            ))}
          </View>
        </>
      )}
      <LockedNote locked={data.locked} signedIn={signedIn} />
      {full && data.unavailable.length > 0 && <Text style={styles.fine}>Not tracked by this platform: {data.unavailable.map((u) => u.replaceAll("_", " ")).join(", ")}.</Text>}
      {data.limitations.map((l) => (
        <Text key={l} style={styles.warn}>{l}</Text>
      ))}
    </View>
  )
}

export function PlayerAnalytics({ playerId, showSeasons = true }: { playerId: number; showSeasons?: boolean }) {
  const { user } = useAuth()
  const { data, error, loading } = useAsync(() => api.getPlayerAnalytics(playerId), `player-analytics:${playerId}:${user?.id ?? "anon"}`)
  return (
    <Card>
      <SectionTitle>Performance</SectionTitle>
      {loading && !data && <Text style={styles.fine}>Loading…</Text>}
      {error && !data && <Text style={styles.fine}>Performance data isn&apos;t available right now.</Text>}
      {data && (data.seasons.length > 0 || data.tier === "full" || data.locked.length > 0 ? (
        <PlayerAnalyticsView data={data} signedIn={!!user} showSeasons={showSeasons} />
      ) : (
        <Text style={styles.fine}>No performance data has been supplied for this player yet.</Text>
      ))}
    </Card>
  )
}

const styles = StyleSheet.create({
  sub: { color: theme.textMuted, fontSize: 11, fontWeight: "700", textTransform: "uppercase", marginBottom: 4 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.border },
  label: { color: theme.textMuted, fontSize: 13, flex: 1 },
  value: { color: theme.text, fontSize: 13, fontWeight: "700" },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  cell: { width: "25%", paddingVertical: 4 },
  trend: { flexDirection: "row", alignItems: "flex-end", gap: 4, height: 44 },
  fine: { color: theme.textMuted, fontSize: 10, lineHeight: 14 },
  warn: { color: "rgba(253,230,138,0.75)", fontSize: 11 },
})

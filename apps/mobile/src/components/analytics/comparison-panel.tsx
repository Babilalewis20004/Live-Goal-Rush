import { StyleSheet, Text, View } from "react-native"

import { LockedNote } from "@/components/analytics/premium-gate"
import { Card } from "@/components/match-centre/ui"
import { useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { comparisonShares, formatNumber, leader, rowSummary } from "@/lib/analytics"
import { theme } from "@/theme"
import type { ComparisonRow, FormSummaryOut, MatchComparisonOut } from "@/types/api"

function Row({ row, names }: { row: ComparisonRow; names: { home: string; away: string } }) {
  const shares = comparisonShares(row)
  const side = leader(row)
  return (
    <View style={styles.rowWrap} accessible accessibilityLabel={rowSummary(row, names)}>
      <View style={styles.rowTop}>
        <Text style={[styles.value, { textAlign: "left" }, side === "home" && styles.lead]}>{formatNumber(row.home)}</Text>
        <Text style={styles.label}>{row.label}</Text>
        <Text style={[styles.value, { textAlign: "right" }, side === "away" && styles.lead]}>{formatNumber(row.away)}</Text>
      </View>
      {shares && (
        <View style={styles.bars}>
          <View style={{ flex: Math.max(shares.home, 1), backgroundColor: side === "home" ? theme.emerald : "rgba(255,255,255,0.3)", borderRadius: 3 }} />
          <View style={{ flex: Math.max(shares.away, 1), backgroundColor: side === "away" ? theme.emerald : "rgba(255,255,255,0.3)", borderRadius: 3 }} />
        </View>
      )}
      {(row.home === null || row.away === null) && <Text style={styles.fine}>Not enough data for one side.</Text>}
    </View>
  )
}

function FormLine({ title, sequence, summary }: { title: string; sequence: string; summary: FormSummaryOut }) {
  return (
    <View style={{ marginTop: 8 }} accessible accessibilityLabel={`${title} form, oldest to newest: ${sequence.split("").join(", ")}. ${summary.wins} wins, ${summary.draws} draws, ${summary.losses} losses.`}>
      <Text style={styles.team}>{title}</Text>
      <Text style={styles.sequence}>{sequence || "no recent matches"}</Text>
      <Text style={styles.fine}>
        {summary.wins}W {summary.draws}D {summary.losses}L · {summary.goals_for}–{summary.goals_against} goals
        {summary.limitation ? ` · ${summary.limitation}` : ""}
      </Text>
    </View>
  )
}

export function ComparisonView({ data, signedIn }: { data: MatchComparisonOut; signedIn: boolean }) {
  const names = { home: data.home_team.name, away: data.away_team.name }
  return (
    <Card>
      <View style={styles.rowTop}>
        <Text style={styles.title} accessibilityRole="header">Team comparison</Text>
        <Text style={styles.fine}>Last {data.form_window} before kick-off</Text>
      </View>
      <View style={[styles.rowTop, { marginTop: 8 }]}>
        <Text style={[styles.team, { flex: 1 }]} numberOfLines={1}>{names.home}</Text>
        <Text style={[styles.team, { flex: 1, textAlign: "right" }]} numberOfLines={1}>{names.away}</Text>
      </View>
      {data.home_form && <FormLine title={names.home} sequence={data.home_sequence} summary={data.home_form} />}
      {data.away_form && <FormLine title={names.away} sequence={data.away_sequence} summary={data.away_form} />}
      <View style={{ marginTop: 6 }}>
        {data.rows.map((r) => (
          <Row key={r.key} row={r} names={names} />
        ))}
      </View>
      {data.head_to_head && data.head_to_head.total_meetings ? (
        <Text style={[styles.muted, { marginTop: 8 }]}>
          Head to head ({data.head_to_head.total_meetings} meetings): {names.home} {data.head_to_head.home_team_wins} wins, {data.head_to_head.draws} draws, {names.away} {data.head_to_head.away_team_wins} wins
          {data.head_to_head.average_goals !== null && data.head_to_head.average_goals !== undefined ? `; ${formatNumber(data.head_to_head.average_goals)} goals per game` : ""}.
        </Text>
      ) : null}
      <LockedNote locked={data.locked} signedIn={signedIn} />
      {data.limitations.map((l) => (
        <Text key={l} style={styles.fine}>Note: {l}</Text>
      ))}
    </Card>
  )
}

export function ComparisonPanel({ matchId, nudge = 0 }: { matchId: number; nudge?: number }) {
  const { user } = useAuth()
  const { data, error, loading } = useAsync(() => api.getMatchComparison(matchId), `comparison:${matchId}:${user?.id ?? "anon"}`, nudge)
  if (loading && !data) return <Card><Text style={styles.muted}>Loading comparison…</Text></Card>
  if (error || !data) {
    return (
      <Card>
        <Text style={styles.title} accessibilityRole="header">Team comparison</Text>
        <Text style={styles.muted}>The comparison isn&apos;t available right now.</Text>
      </Card>
    )
  }
  return <ComparisonView data={data} signedIn={!!user} />
}

const styles = StyleSheet.create({
  title: { color: theme.text, fontSize: 14, fontWeight: "700" },
  team: { color: theme.textMuted, fontSize: 12, fontWeight: "600" },
  rowWrap: { paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.border },
  rowTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  value: { color: "rgba(255,255,255,0.85)", fontSize: 15, fontWeight: "700", width: 60 },
  lead: { color: theme.emerald },
  label: { color: theme.textMuted, fontSize: 12, flex: 1, textAlign: "center" },
  bars: { flexDirection: "row", gap: 2, height: 5, marginTop: 4 },
  sequence: { color: theme.text, fontSize: 15, letterSpacing: 4, fontFamily: undefined },
  muted: { color: theme.textMuted, fontSize: 12, lineHeight: 18 },
  fine: { color: theme.textMuted, fontSize: 10, lineHeight: 14, marginTop: 2 },
})

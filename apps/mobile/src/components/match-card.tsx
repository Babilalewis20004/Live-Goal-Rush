import { Link } from "expo-router"
import { Pressable, StyleSheet, Text, View } from "react-native"
import type { MatchSummary } from "@/types/api"
import { formatKickoff } from "@/lib/format"
import { theme } from "@/theme"
import { TeamBadge } from "./team-badge"

function StatusLabel({ match }: { match: MatchSummary }) {
  if (match.status === "live") {
    return <Text style={[styles.statusText, { color: theme.emerald }]}>{match.minute}&apos;</Text>
  }
  if (match.status === "halftime") {
    return <Text style={[styles.statusText, { color: theme.amber }]}>HT</Text>
  }
  if (match.status === "finished") {
    return <Text style={[styles.statusText, { color: theme.textFaint }]}>FT</Text>
  }
  if (match.status === "postponed" || match.status === "cancelled") {
    return <Text style={[styles.statusText, { color: theme.textFaint }]}>{match.status.toUpperCase()}</Text>
  }
  return <Text style={[styles.statusText, { color: theme.textMuted }]}>{formatKickoff(match.kickoff_time)}</Text>
}

function Score({ value, live, dim }: { value: number; live?: boolean; dim?: boolean }) {
  return (
    <Text
      style={[
        styles.score,
        live ? { color: theme.emerald } : dim ? { color: theme.textFaint } : { color: theme.text },
      ]}
    >
      {value}
    </Text>
  )
}

export function MatchCard({ match }: { match: MatchSummary }) {
  const isLive = match.status === "live"
  const scheduled = match.status === "scheduled"
  const homeWin = match.home_score > match.away_score
  const awayWin = match.away_score > match.home_score

  return (
    <Link href={{ pathname: "/match/[id]", params: { id: String(match.id) } }} asChild>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`${match.home_team.name} versus ${match.away_team.name}`}
        style={styles.row}
      >
        {isLive && <View style={styles.liveBar} />}
        <View style={styles.statusCol}>
          <StatusLabel match={match} />
        </View>
        <View style={styles.teams}>
          <View style={styles.teamRow}>
            <View style={styles.teamName}>
              <TeamBadge name={match.home_team.name} shortName={match.home_team.short_name} logoUrl={match.home_team.logo_url} size={22} />
              <Text
                numberOfLines={1}
                style={[styles.teamText, homeWin && !scheduled ? styles.teamTextWin : null]}
              >
                {match.home_team.name}
              </Text>
            </View>
            {!scheduled && <Score value={match.home_score} live={isLive} dim={awayWin} />}
          </View>
          <View style={[styles.teamRow, { marginTop: 6 }]}>
            <View style={styles.teamName}>
              <TeamBadge name={match.away_team.name} shortName={match.away_team.short_name} logoUrl={match.away_team.logo_url} size={22} />
              <Text
                numberOfLines={1}
                style={[styles.teamText, awayWin && !scheduled ? styles.teamTextWin : null]}
              >
                {match.away_team.name}
              </Text>
            </View>
            {!scheduled && <Score value={match.away_score} live={isLive} dim={homeWin} />}
          </View>
        </View>
      </Pressable>
    </Link>
  )
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.border,
  },
  liveBar: {
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    width: 3,
    backgroundColor: theme.emerald,
  },
  statusCol: {
    width: 40,
    alignItems: "center",
  },
  statusText: {
    fontSize: 11,
    fontWeight: "700",
  },
  teams: {
    flex: 1,
    minWidth: 0,
  },
  teamRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  teamName: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flex: 1,
    minWidth: 0,
  },
  teamText: {
    color: theme.textMuted,
    fontSize: 14,
    flexShrink: 1,
  },
  teamTextWin: {
    color: theme.text,
    fontWeight: "700",
  },
  score: {
    fontSize: 15,
    fontWeight: "700",
    minWidth: 20,
    textAlign: "center",
  },
})

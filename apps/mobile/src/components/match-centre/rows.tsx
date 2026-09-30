import { Ionicons } from "@expo/vector-icons"
import { Link } from "expo-router"
import { Pressable, StyleSheet, Text, View } from "react-native"
import { TeamBadge } from "@/components/team-badge"
import { formatKickoff, formatKickoffDate } from "@/lib/format"
import {
  describeEvent,
  formatStat,
  statusDisplay,
  zoneTone,
  type StatRow,
  type TimelineItem,
  type ZoneTone,
} from "@/lib/match-centre"
import { theme } from "@/theme"
import type {
  HeadToHeadOut,
  LineupPlayerOut,
  MatchDetail,
  PlayerOut,
  StandingEntry,
  TeamLineupOut,
  TopScorerOut,
} from "@/types/api"

// -- header ---------------------------------------------------------------------------------

/** Match header. Driven entirely by the app's normalized status via
 * `statusDisplay` -- never a provider status string. */
export function MatchHeader({ match }: { match: MatchDetail }) {
  const status = statusDisplay(match)
  const summary = status.showScore
    ? `${match.home_team.name} ${match.home_score}, ${match.away_team.name} ${match.away_score}`
    : `${match.home_team.name} versus ${match.away_team.name}`

  return (
    <View
      style={styles.headerCard}
      accessible
      accessibilityLabel={`${summary}. ${status.label}${status.detail ? ` ${status.detail}` : ""}`}
    >
      <Text style={styles.competition}>{match.competition.name}</Text>
      <View style={styles.scoreRow}>
        <View style={styles.teamCol}>
          <TeamBadge name={match.home_team.name} shortName={match.home_team.short_name} logoUrl={match.home_team.logo_url} size={48} />
          <Text style={styles.teamName} numberOfLines={1}>
            {match.home_team.name}
          </Text>
        </View>

        <View style={styles.scoreCol}>
          {status.showScore ? (
            <Text style={styles.score}>
              {match.home_score} – {match.away_score}
            </Text>
          ) : (
            <Text style={styles.score}>{status.kind === "upcoming" ? status.label : "–"}</Text>
          )}
          {status.kind === "upcoming" ? (
            <Text style={styles.statusFaint}>{status.detail}</Text>
          ) : (
            <View style={[styles.pill, status.isLive && styles.pillLive]}>
              <Text style={[styles.pillText, status.isLive && styles.pillTextLive]}>{status.label}</Text>
            </View>
          )}
          {status.kind === "live" && status.detail && <Text style={styles.minute}>{status.detail}</Text>}
        </View>

        <View style={styles.teamCol}>
          <TeamBadge name={match.away_team.name} shortName={match.away_team.short_name} logoUrl={match.away_team.logo_url} size={48} />
          <Text style={styles.teamName} numberOfLines={1}>
            {match.away_team.name}
          </Text>
        </View>
      </View>
      <Text style={styles.meta}>
        {formatKickoffDate(match.kickoff_time)} · {formatKickoff(match.kickoff_time)} UTC
        {match.venue ? `  ·  ${match.venue}` : ""}
      </Text>
    </View>
  )
}

// -- timeline -------------------------------------------------------------------------------------

function TimelineIconView({ item }: { item: TimelineItem }) {
  switch (item.icon) {
    case "yellow_card":
      return <View style={[styles.card, { backgroundColor: theme.amber }]} />
    case "second_yellow":
      return <View style={[styles.card, { backgroundColor: theme.red }]} />
    case "red_card":
      return <View style={[styles.card, { backgroundColor: theme.red }]} />
    case "substitution":
      return <Ionicons name="swap-horizontal" size={14} color={theme.emerald} />
    case "var":
      return <Text style={styles.varBadge}>VAR</Text>
    case "penalty_missed":
      return <Ionicons name="close-circle" size={14} color={theme.red} />
    case "own_goal":
      return <Ionicons name="football" size={14} color={theme.red} />
    case "goal":
    case "penalty":
      return <Ionicons name="football" size={14} color={theme.emerald} />
    default:
      return <View style={styles.dot} />
  }
}

export function TimelineRow({ item }: { item: TimelineItem }) {
  return (
    <View style={styles.timelineRow} accessible accessibilityLabel={item.accessibleLabel}>
      <Text style={styles.minuteLabel}>{item.minuteLabel}</Text>
      <TimelineIconView item={item} />
      <View style={{ flex: 1 }}>
        <Text style={[styles.eventTitle, item.isGoal && styles.eventTitleGoal]} numberOfLines={1}>
          {item.title}
        </Text>
        {item.subtitle && (
          <Text style={styles.eventSubtitle} numberOfLines={1}>
            {item.subtitle}
          </Text>
        )}
      </View>
      <Text style={styles.sideTag}>{item.side === "home" ? "H" : item.side === "away" ? "A" : ""}</Text>
    </View>
  )
}

export function buildTimeline(match: MatchDetail): TimelineItem[] {
  return [...match.events]
    .sort((a, b) => a.minute - b.minute || (a.extra_minute ?? 0) - (b.extra_minute ?? 0) || a.id - b.id)
    .map((e) => describeEvent(e, match.home_team.id, match.away_team.id))
}

// -- statistics -------------------------------------------------------------------------------------

export function StatRowView({ row, homeName, awayName }: { row: StatRow; homeName: string; awayName: string }) {
  const home = formatStat(row.home, row.format)
  const away = formatStat(row.away, row.format)
  return (
    <View style={styles.statRow} accessible accessibilityLabel={`${row.label}: ${homeName} ${home}, ${awayName} ${away}`}>
      <View style={styles.statNumbers}>
        <Text style={styles.statValue}>{home}</Text>
        <Text style={styles.statLabel}>{row.label}</Text>
        <Text style={[styles.statValue, { textAlign: "right" }]}>{away}</Text>
      </View>
      <View style={styles.bar}>
        <View style={{ flex: row.homeShare, backgroundColor: theme.emerald, borderRadius: 3 }} />
        <View style={{ flex: 1 - row.homeShare, backgroundColor: "#38bdf8", borderRadius: 3 }} />
      </View>
    </View>
  )
}

// -- lineups -----------------------------------------------------------------------------------------

export function LineupHeaderRow({ lineup }: { lineup: TeamLineupOut }) {
  return (
    <View style={styles.lineupHeader}>
      <TeamBadge name={lineup.team.name} shortName={lineup.team.short_name} logoUrl={lineup.team.logo_url} size={22} />
      <Text style={styles.lineupTeam} numberOfLines={1}>
        {lineup.team.name}
      </Text>
      {/* Only shown when the provider states a formation -- never inferred. */}
      {lineup.formation && <Text style={styles.formation}>{lineup.formation}</Text>}
    </View>
  )
}

export function LineupPlayerRow({ entry }: { entry: LineupPlayerOut }) {
  const moves = [
    entry.subbed_out_minute != null ? `Substituted off ${entry.subbed_out_minute} minutes` : null,
    entry.subbed_in_minute != null ? `Substituted on ${entry.subbed_in_minute} minutes` : null,
  ].filter(Boolean)
  const body = (
    <View
      style={styles.playerRow}
      accessible
      accessibilityLabel={`${entry.shirt_number != null ? `Number ${entry.shirt_number}, ` : ""}${entry.player.name}${entry.position ? `, ${entry.position}` : ""}${moves.length ? `, ${moves.join(", ")}` : ""}`}
    >
      <Text style={styles.shirt}>{entry.shirt_number ?? "–"}</Text>
      <Text style={styles.playerName} numberOfLines={1}>
        {entry.player.name}
      </Text>
      {entry.subbed_out_minute != null && (
        <Text style={[styles.subTag, { color: theme.red }]}>↓ {entry.subbed_out_minute}&apos;</Text>
      )}
      {entry.subbed_in_minute != null && (
        <Text style={[styles.subTag, { color: theme.emerald }]}>↑ {entry.subbed_in_minute}&apos;</Text>
      )}
    </View>
  )
  if (entry.player.id <= 0) return body
  return (
    <Link href={{ pathname: "/player/[id]", params: { id: String(entry.player.id) } }} asChild>
      <Pressable accessibilityRole="link">{body}</Pressable>
    </Link>
  )
}

// -- head to head --------------------------------------------------------------------------------------

function yearOf(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" })
}

export function HeadToHeadSection({ match, data }: { match: MatchDetail; data: HeadToHeadOut }) {
  const total = data.meetings.length
  return (
    <View style={{ gap: 8 }}>
      <View style={styles.formHeader}>
        <Text style={styles.sectionTitleInline}>Head to head</Text>
        <Text style={styles.faint}>
          {total > 0 ? `Last ${total} since ${yearOf(data.period_start)}` : `Since ${yearOf(data.period_start)}`}
        </Text>
      </View>
      {total === 0 ? (
        <Text style={styles.faint}>No previous meetings stored for these teams.</Text>
      ) : (
        <>
          <View style={styles.h2hCounts} accessible accessibilityLabel={`Head to head: ${match.home_team.name} ${data.home_team_wins} wins, ${data.draws} draws, ${match.away_team.name} ${data.away_team_wins} wins`}>
            {[
              [data.home_team_wins, `${match.home_team.short_name ?? match.home_team.name} wins`],
              [data.draws, "Draws"],
              [data.away_team_wins, `${match.away_team.short_name ?? match.away_team.name} wins`],
            ].map(([value, label]) => (
              <View key={String(label)} style={styles.h2hCount}>
                <Text style={styles.h2hValue}>{value}</Text>
                <Text style={styles.faint} numberOfLines={1}>
                  {label}
                </Text>
              </View>
            ))}
          </View>
          {data.meetings.map((m) => (
            <Link key={m.match_id} href={{ pathname: "/match/[id]", params: { id: String(m.match_id) } }} asChild>
              <Pressable style={styles.meeting} accessibilityRole="link">
                <Text style={styles.meetingDate}>{formatKickoffDate(m.kickoff_time)}</Text>
                <Text style={styles.meetingTeam} numberOfLines={1}>
                  {m.home_team.name}
                </Text>
                <Text style={styles.meetingScore}>
                  {m.home_score} – {m.away_score}
                </Text>
                <Text style={[styles.meetingTeam, { textAlign: "right" }]} numberOfLines={1}>
                  {m.away_team.name}
                </Text>
              </Pressable>
            </Link>
          ))}
        </>
      )}
    </View>
  )
}

// -- standings / scorers / squad ------------------------------------------------------------------------

const ZONE_COLOR: Record<ZoneTone, string> = {
  positive: theme.emerald,
  europe: "#38bdf8",
  negative: theme.red,
  neutral: "transparent",
}

export function StandingsHeaderRow({ group, season }: { group: string; season: string }) {
  return (
    <View style={styles.tableHead}>
      <Text style={[styles.th, { width: 24 }]}>#</Text>
      <Text style={[styles.th, { flex: 1 }]}>{group ? `${group}` : "Team"}</Text>
      <Text style={[styles.th, styles.num]}>P</Text>
      <Text style={[styles.th, styles.num]}>W</Text>
      <Text style={[styles.th, styles.num]}>D</Text>
      <Text style={[styles.th, styles.num]}>L</Text>
      <Text style={[styles.th, styles.num]}>GD</Text>
      <Text style={[styles.th, styles.pts]}>Pts</Text>
      <Text style={styles.seasonTag}>{season}</Text>
    </View>
  )
}

export function StandingRowView({
  row,
  highlighted,
}: {
  row: StandingEntry
  highlighted?: boolean
}) {
  const gd = row.goal_difference > 0 ? `+${row.goal_difference}` : String(row.goal_difference)
  return (
    <Link href={{ pathname: "/team/[id]", params: { id: String(row.team.id) } }} asChild>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`${row.position}. ${row.team.name}, played ${row.played}, won ${row.won}, drawn ${row.drawn}, lost ${row.lost}, goal difference ${gd}, ${row.points} points${row.description ? `, ${row.description}` : ""}`}
        style={[styles.tableRow, highlighted && styles.tableRowHighlight]}
      >
        <View style={[styles.zone, { backgroundColor: ZONE_COLOR[zoneTone(row.description)] }]} />
        <Text style={[styles.td, { width: 24 }]}>{row.position}</Text>
        <View style={styles.tableTeam}>
          <TeamBadge name={row.team.name} shortName={row.team.short_name} logoUrl={row.team.logo_url} size={20} />
          <Text style={[styles.tdTeam, highlighted && { fontWeight: "700", color: theme.text }]} numberOfLines={1}>
            {row.team.name}
          </Text>
        </View>
        <Text style={[styles.td, styles.num]}>{row.played}</Text>
        <Text style={[styles.td, styles.num]}>{row.won}</Text>
        <Text style={[styles.td, styles.num]}>{row.drawn}</Text>
        <Text style={[styles.td, styles.num]}>{row.lost}</Text>
        <Text style={[styles.td, styles.num]}>{gd}</Text>
        <Text style={[styles.td, styles.pts, { color: theme.text, fontWeight: "700" }]}>{row.points}</Text>
      </Pressable>
    </Link>
  )
}

export function StandingsLegend({ standings }: { standings: StandingEntry[] }) {
  const legend = [...new Set(standings.map((r) => r.description).filter((d): d is string => !!d))]
  if (legend.length === 0) return null
  return (
    <View style={styles.legend}>
      {legend.map((d) => (
        <View key={d} style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: zoneTone(d) === "neutral" ? "rgba(255,255,255,0.2)" : ZONE_COLOR[zoneTone(d)] }]} />
          <Text style={styles.faint}>{d}</Text>
        </View>
      ))}
    </View>
  )
}

export function TopScorerRow({ scorer }: { scorer: TopScorerOut }) {
  return (
    <Link href={{ pathname: "/player/[id]", params: { id: String(scorer.player.id) } }} asChild>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`${scorer.rank}. ${scorer.player.name}${scorer.team ? `, ${scorer.team.name}` : ""}, ${scorer.goals} goals${scorer.assists != null ? `, ${scorer.assists} assists` : ""}`}
        style={styles.scorerRow}
      >
        <Text style={[styles.td, { width: 24 }]}>{scorer.rank}</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.playerName} numberOfLines={1}>
            {scorer.player.name}
          </Text>
          {scorer.team && (
            <Text style={styles.faint} numberOfLines={1}>
              {scorer.team.name}
            </Text>
          )}
        </View>
        <Text style={[styles.td, styles.num]}>{scorer.appearances ?? "–"}</Text>
        <Text style={[styles.td, styles.num]}>{scorer.assists ?? "–"}</Text>
        <Text style={[styles.td, styles.pts, { color: theme.text, fontWeight: "700" }]}>{scorer.goals}</Text>
      </Pressable>
    </Link>
  )
}

export function SquadRow({ player }: { player: PlayerOut }) {
  return (
    <Link href={{ pathname: "/player/[id]", params: { id: String(player.id) } }} asChild>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`${player.shirt_number != null ? `Number ${player.shirt_number}, ` : ""}${player.name}${player.position ? `, ${player.position}` : ""}`}
        style={styles.playerRow}
      >
        <Text style={styles.shirt}>{player.shirt_number ?? "–"}</Text>
        <Text style={styles.playerName} numberOfLines={1}>
          {player.name}
        </Text>
        <Text style={styles.faint}>{player.position ?? ""}</Text>
      </Pressable>
    </Link>
  )
}

const styles = StyleSheet.create({
  headerCard: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
  },
  competition: {
    color: theme.textFaint,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    textAlign: "center",
    marginBottom: 16,
  },
  scoreRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  teamCol: { flex: 1, alignItems: "center", gap: 8 },
  teamName: { color: theme.text, fontSize: 12, fontWeight: "600", textAlign: "center" },
  scoreCol: { alignItems: "center", gap: 6, paddingHorizontal: 8 },
  score: { color: theme.text, fontSize: 30, fontWeight: "800", fontVariant: ["tabular-nums"] },
  pill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  pillLive: { backgroundColor: "rgba(52,211,153,0.15)" },
  pillText: { color: theme.textFaint, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  pillTextLive: { color: theme.emerald },
  statusFaint: { color: theme.textMuted, fontSize: 12, fontWeight: "600" },
  minute: { color: theme.emerald, fontSize: 14, fontWeight: "700" },
  meta: { color: theme.textFaint, fontSize: 11, textAlign: "center", marginTop: 16 },
  timelineRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.border,
  },
  minuteLabel: { color: theme.textMuted, fontSize: 12, fontWeight: "700", width: 44, fontVariant: ["tabular-nums"] },
  eventTitle: { color: theme.textMuted, fontSize: 14 },
  eventTitleGoal: { color: theme.text, fontWeight: "700" },
  eventSubtitle: { color: theme.textFaint, fontSize: 11 },
  sideTag: { color: theme.textFaint, fontSize: 10, fontWeight: "700", width: 14, textAlign: "center" },
  card: { width: 10, height: 14, borderRadius: 2 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.textFaint },
  varBadge: { color: "#7dd3fc", fontSize: 9, fontWeight: "800" },
  statRow: { paddingVertical: 10, gap: 6 },
  statNumbers: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  statValue: { color: theme.text, fontSize: 15, fontWeight: "700", width: 56 },
  statLabel: { color: theme.textMuted, fontSize: 12 },
  bar: { flexDirection: "row", height: 6, gap: 3 },
  lineupHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingTop: 16,
    paddingBottom: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.border,
  },
  lineupTeam: { color: theme.text, fontSize: 14, fontWeight: "700", flex: 1 },
  formation: { color: theme.textMuted, fontSize: 12, fontWeight: "700" },
  playerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 44,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.border,
  },
  shirt: { color: theme.textFaint, fontSize: 12, fontWeight: "700", width: 24, textAlign: "right" },
  playerName: { color: theme.text, fontSize: 14, flex: 1 },
  subTag: { fontSize: 11, fontWeight: "700" },
  formHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: 8 },
  sectionTitleInline: { color: theme.text, fontSize: 12, fontWeight: "700" },
  faint: { color: theme.textFaint, fontSize: 11 },
  h2hCounts: { flexDirection: "row", gap: 8 },
  h2hCount: { flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.05)" },
  h2hValue: { color: theme.text, fontSize: 18, fontWeight: "800" },
  meeting: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 40 },
  meetingDate: { color: theme.textFaint, fontSize: 10, width: 64 },
  meetingTeam: { color: theme.textMuted, fontSize: 12, flex: 1 },
  meetingScore: { color: theme.text, fontSize: 12, fontWeight: "700" },
  tableHead: { flexDirection: "row", alignItems: "center", paddingVertical: 8, paddingLeft: 4 },
  th: { color: theme.textFaint, fontSize: 10, fontWeight: "700", textTransform: "uppercase" },
  seasonTag: { color: theme.textFaint, fontSize: 10, marginLeft: 6 },
  tableRow: {
    flexDirection: "row",
    alignItems: "center",
    minHeight: 40,
    paddingLeft: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.border,
  },
  tableRowHighlight: { backgroundColor: "rgba(255,255,255,0.07)" },
  zone: { position: "absolute", left: 0, top: 6, bottom: 6, width: 3, borderRadius: 2 },
  td: { color: theme.textMuted, fontSize: 12 },
  tdTeam: { color: theme.textMuted, fontSize: 13, flex: 1 },
  tableTeam: { flex: 1, flexDirection: "row", alignItems: "center", gap: 8 },
  num: { width: 26, textAlign: "center" },
  pts: { width: 32, textAlign: "center" },
  legend: { flexDirection: "row", flexWrap: "wrap", gap: 12, paddingTop: 10 },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
  scorerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    minHeight: 48,
    paddingLeft: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.border,
  },
})

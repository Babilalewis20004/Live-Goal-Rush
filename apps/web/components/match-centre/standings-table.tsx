import Link from "next/link"
import { TeamBadge } from "@/components/team-badge"
import { groupStandings, zoneTone, type ZoneTone } from "@/lib/match-centre"
import type { StandingEntry } from "@/types/api"

const ZONE_BAR: Record<ZoneTone, string> = {
  positive: "bg-emerald-400",
  europe: "bg-sky-400",
  negative: "bg-red-500",
  neutral: "bg-transparent",
}

function Table({
  rows,
  highlightTeamIds,
  caption,
}: {
  rows: StandingEntry[]
  highlightTeamIds: number[]
  caption: string
}) {
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="text-[11px] uppercase tracking-wide text-white/40">
          <th scope="col" className="w-9 py-2 pl-3 text-left font-medium">
            <abbr title="Position" className="no-underline">#</abbr>
          </th>
          <th scope="col" className="py-2 text-left font-medium">Team</th>
          <th scope="col" className="w-7 py-2 text-center font-medium"><abbr title="Played" className="no-underline">P</abbr></th>
          <th scope="col" className="w-7 py-2 text-center font-medium"><abbr title="Won" className="no-underline">W</abbr></th>
          <th scope="col" className="w-7 py-2 text-center font-medium"><abbr title="Drawn" className="no-underline">D</abbr></th>
          <th scope="col" className="w-7 py-2 text-center font-medium"><abbr title="Lost" className="no-underline">L</abbr></th>
          <th scope="col" className="hidden w-8 py-2 text-center font-medium sm:table-cell"><abbr title="Goals for" className="no-underline">GF</abbr></th>
          <th scope="col" className="hidden w-8 py-2 text-center font-medium sm:table-cell"><abbr title="Goals against" className="no-underline">GA</abbr></th>
          <th scope="col" className="w-9 py-2 text-center font-medium"><abbr title="Goal difference" className="no-underline">GD</abbr></th>
          <th scope="col" className="w-10 py-2 pr-3 text-center font-medium"><abbr title="Points" className="no-underline">Pts</abbr></th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/[0.06]">
        {rows.map((row) => {
          const tone = zoneTone(row.description)
          const highlighted = highlightTeamIds.includes(row.team.id)
          return (
            <tr key={`${row.group_name}-${row.team.id}`} className={highlighted ? "bg-white/[0.06]" : undefined}>
              <td className="relative py-2 pl-3 text-white/60">
                <span className={`absolute inset-y-1 left-0 w-0.5 rounded-full ${ZONE_BAR[tone]}`} aria-hidden="true" />
                {row.position}
                {row.description && <span className="sr-only">, {row.description}</span>}
              </td>
              <td className="py-2">
                <Link href={`/team/${row.team.id}`} className="flex items-center gap-2 hover:underline">
                  <TeamBadge name={row.team.name} shortName={row.team.short_name} logoUrl={row.team.logo_url} size={20} />
                  <span className={["truncate", highlighted ? "font-semibold text-white" : "text-white/90"].join(" ")}>
                    {row.team.name}
                  </span>
                </Link>
              </td>
              <td className="py-2 text-center text-white/60">{row.played}</td>
              <td className="py-2 text-center text-white/60">{row.won}</td>
              <td className="py-2 text-center text-white/60">{row.drawn}</td>
              <td className="py-2 text-center text-white/60">{row.lost}</td>
              <td className="hidden py-2 text-center text-white/60 sm:table-cell">{row.goals_for}</td>
              <td className="hidden py-2 text-center text-white/60 sm:table-cell">{row.goals_against}</td>
              <td className="py-2 text-center text-white/60">{row.goal_difference > 0 ? `+${row.goal_difference}` : row.goal_difference}</td>
              <td className="py-2 pr-3 text-center font-semibold text-white">{row.points}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** A competition table. Handles single tables and group stages (one table per
 * `group_name`), shows the provider's own classification text as a legend
 * (the app never decides what qualifies or is relegated), and labels the
 * season so a past season is never mistaken for the current one. */
export function StandingsTable({
  standings,
  highlightTeamIds = [],
  title = "Standings",
}: {
  standings: StandingEntry[]
  highlightTeamIds?: number[]
  title?: string
}) {
  const groups = groupStandings(standings)
  const season = standings[0]?.season
  const legend = [...new Set(standings.map((r) => r.description).filter((d): d is string => !!d))]

  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
      <div className="flex items-baseline justify-between border-b border-white/[0.06] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        {season && <span className="text-[11px] text-white/45">Season {season}</span>}
      </div>
      {groups.map(({ group, rows }) => (
        <div key={group || "table"}>
          {group && <h3 className="px-4 pb-1 pt-3 text-xs font-semibold text-white/70">{group}</h3>}
          <Table rows={rows} highlightTeamIds={highlightTeamIds} caption={group ? `${title}, ${group}` : title} />
        </div>
      ))}
      {legend.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 border-t border-white/[0.06] px-4 py-2.5 text-[10px] text-white/45">
          {legend.map((d) => (
            <li key={d} className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${ZONE_BAR[zoneTone(d)] === "bg-transparent" ? "bg-white/20" : ZONE_BAR[zoneTone(d)]}`} aria-hidden="true" />
              {d}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

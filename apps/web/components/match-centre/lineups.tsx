import Link from "next/link"
import { ArrowRightLeft } from "lucide-react"
import { TeamBadge } from "@/components/team-badge"
import type { LineupPlayerOut, TeamLineupOut } from "@/types/api"

function PlayerRow({ entry }: { entry: LineupPlayerOut }) {
  const name = entry.player.id > 0 ? (
    <Link href={`/player/${entry.player.id}`} className="truncate hover:underline">
      {entry.player.name}
    </Link>
  ) : (
    <span className="truncate">{entry.player.name}</span>
  )
  const moves = [
    entry.subbed_out_minute != null ? `Substituted off ${entry.subbed_out_minute} minutes` : null,
    entry.subbed_in_minute != null ? `Substituted on ${entry.subbed_in_minute} minutes` : null,
  ].filter(Boolean)

  return (
    <li className="flex items-center gap-3 py-1.5 text-sm text-white/85">
      <span className="w-6 shrink-0 text-right text-xs font-semibold tabular-nums text-white/45">
        {entry.shirt_number ?? "–"}
      </span>
      {name}
      {entry.position && <span className="hidden shrink-0 text-[10px] text-white/35 sm:inline">{entry.position}</span>}
      <span className="ml-auto flex shrink-0 items-center gap-2 text-[10px] tabular-nums">
        {entry.subbed_out_minute != null && (
          <span className="flex items-center gap-0.5 text-red-400" title={`Off ${entry.subbed_out_minute}'`}>
            <ArrowRightLeft className="h-3 w-3" aria-hidden="true" />
            {entry.subbed_out_minute}&apos;
          </span>
        )}
        {entry.subbed_in_minute != null && (
          <span className="flex items-center gap-0.5 text-emerald-400" title={`On ${entry.subbed_in_minute}'`}>
            <ArrowRightLeft className="h-3 w-3" aria-hidden="true" />
            {entry.subbed_in_minute}&apos;
          </span>
        )}
        {moves.length > 0 && <span className="sr-only">{moves.join(", ")}</span>}
      </span>
    </li>
  )
}

function TeamLineup({ lineup }: { lineup: TeamLineupOut }) {
  return (
    <section
      aria-label={`${lineup.team.name} lineup`}
      className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"
    >
      <header className="flex items-center gap-2.5 border-b border-white/[0.06] px-4 py-3">
        <TeamBadge name={lineup.team.name} shortName={lineup.team.short_name} logoUrl={lineup.team.logo_url} size={24} />
        <h3 className="text-sm font-semibold text-white">{lineup.team.name}</h3>
        {/* Only shown when the provider states a formation -- never inferred. */}
        {lineup.formation && (
          <span className="ml-auto rounded-md bg-white/[0.06] px-2 py-0.5 text-[11px] font-semibold tabular-nums text-white/70">
            {lineup.formation}
          </span>
        )}
      </header>
      <div className="px-4 py-3">
        <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/40">Starting XI</h4>
        <ul className="divide-y divide-white/[0.05]">
          {lineup.starters.map((entry) => (
            <PlayerRow key={entry.player.id} entry={entry} />
          ))}
        </ul>
        {lineup.substitutes.length > 0 && (
          <>
            <h4 className="mb-1 mt-4 text-[11px] font-semibold uppercase tracking-wide text-white/40">Substitutes</h4>
            <ul className="divide-y divide-white/[0.05]">
              {lineup.substitutes.map((entry) => (
                <PlayerRow key={entry.player.id} entry={entry} />
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  )
}

export function Lineups({ home, away }: { home: TeamLineupOut | null; away: TeamLineupOut | null }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {home && <TeamLineup lineup={home} />}
      {away && <TeamLineup lineup={away} />}
    </div>
  )
}

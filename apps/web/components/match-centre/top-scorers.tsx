import Link from "next/link"
import { TeamBadge } from "@/components/team-badge"
import type { TopScorersOut } from "@/types/api"

/** Top scorers for one competition *and season* -- the season is always
 * stated, so historical data is never presented as current. */
export function TopScorers({ data }: { data: TopScorersOut }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
      <div className="flex items-baseline justify-between border-b border-white/[0.06] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Top scorers</h2>
        {data.season && <span className="text-[11px] text-white/45">Season {data.season}</span>}
      </div>
      <table className="w-full text-sm">
        <caption className="sr-only">Top scorers{data.season ? `, season ${data.season}` : ""}</caption>
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-white/40">
            <th scope="col" className="w-9 py-2 pl-4 text-left font-medium">#</th>
            <th scope="col" className="py-2 text-left font-medium">Player</th>
            <th scope="col" className="hidden py-2 text-left font-medium sm:table-cell">Team</th>
            <th scope="col" className="w-9 py-2 text-center font-medium"><abbr title="Appearances" className="no-underline">Apps</abbr></th>
            <th scope="col" className="w-9 py-2 text-center font-medium"><abbr title="Assists" className="no-underline">Ast</abbr></th>
            <th scope="col" className="w-10 py-2 pr-4 text-center font-medium"><abbr title="Goals" className="no-underline">Goals</abbr></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.06]">
          {data.scorers.map((s) => (
            <tr key={s.player.id}>
              <td className="py-2 pl-4 text-white/60">{s.rank}</td>
              <td className="py-2">
                <Link href={`/player/${s.player.id}`} className="block truncate text-white/90 hover:underline">
                  {s.player.name}
                </Link>
                {s.team && <span className="block truncate text-[10px] text-white/40 sm:hidden">{s.team.name}</span>}
              </td>
              <td className="hidden py-2 sm:table-cell">
                {s.team && (
                  <Link href={`/team/${s.team.id}`} className="flex items-center gap-2 text-white/70 hover:underline">
                    <TeamBadge name={s.team.name} shortName={s.team.short_name} logoUrl={s.team.logo_url} size={18} />
                    <span className="truncate">{s.team.name}</span>
                  </Link>
                )}
              </td>
              <td className="py-2 text-center text-white/60">{s.appearances ?? "–"}</td>
              <td className="py-2 text-center text-white/60">{s.assists ?? "–"}</td>
              <td className="py-2 pr-4 text-center font-semibold text-white">{s.goals}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

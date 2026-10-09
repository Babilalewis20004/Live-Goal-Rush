import type { TeamInjuriesOut } from "@/types/api"

const KIND_LABEL = { missing: "Out", doubtful: "Doubtful" } as const
const KIND_STYLE = {
  missing: "bg-red-500/15 text-red-300",
  doubtful: "bg-amber-500/15 text-amber-300",
} as const

function shortDate(iso: string | null): string | null {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" })
}

/** Current absences for a team. Renders nothing unless the provider supplies an
 * injury feed AND there is someone to list: an empty card would read as
 * "no injuries", which the data can't promise. */
export function TeamInjuries({ injuries }: { injuries: TeamInjuriesOut | null }) {
  if (!injuries || !injuries.supported || injuries.items.length === 0) return null
  const matchDate = shortDate(injuries.items[0].match_date)

  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-white">Injuries &amp; doubts</h2>
        {matchDate && <span className="text-[11px] text-white/45">For the match on {matchDate}</span>}
      </div>
      <ul className="divide-y divide-white/[0.05]">
        {injuries.items.map((injury) => (
          <li key={`${injury.player_name}-${injury.match_date}`} className="flex items-center gap-3 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate text-white/85">{injury.player_name}</span>
            {injury.reason && <span className="shrink-0 truncate text-[11px] text-white/45">{injury.reason}</span>}
            <span className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold ${KIND_STYLE[injury.kind]}`}>
              {KIND_LABEL[injury.kind]}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[10px] text-white/30">Reported by the data provider; availability can change before kickoff.</p>
    </section>
  )
}

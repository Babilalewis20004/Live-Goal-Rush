import Link from "next/link"
import type { CompetitionOut } from "@/types/api"
import { LeagueLogo } from "./league-logo"

export function CompetitionCard({ competition }: { competition: CompetitionOut }) {
  return (
    <Link
      href={`/competition/${competition.id}`}
      className="flex items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06]"
    >
      <LeagueLogo name={competition.name} logoUrl={competition.logo_url} size={32} />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-white">{competition.name}</p>
        <p className="text-[11px] text-white/40">{competition.country ?? "International"}</p>
      </div>
    </Link>
  )
}

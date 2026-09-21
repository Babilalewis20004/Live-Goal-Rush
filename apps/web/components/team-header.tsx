import type { TeamOut } from "@/types/api"
import { TeamBadge } from "./team-badge"

export function TeamHeader({ team }: { team: TeamOut }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-5 py-6 backdrop-blur-md">
      <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} size={48} />
      <div className="min-w-0">
        <h1 className="truncate text-lg font-bold text-white">{team.name}</h1>
        {team.country && <p className="text-xs text-white/40">{team.country}</p>}
      </div>
    </div>
  )
}

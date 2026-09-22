import type { CompetitionOut } from "@/types/api"
import { FavouriteButton } from "./favourite-button"
import { LeagueLogo } from "./league-logo"

export function CompetitionHeader({
  competition,
  initialFollowed = false,
}: {
  competition: CompetitionOut
  initialFollowed?: boolean
}) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-5 py-6 backdrop-blur-md">
      <LeagueLogo name={competition.name} logoUrl={competition.logo_url} size={48} />
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-lg font-bold text-white">{competition.name}</h1>
        <p className="text-xs text-white/40">
          {competition.country ?? "International"} · {competition.type}
        </p>
      </div>
      <FavouriteButton kind="competition" id={competition.id} initialFollowed={initialFollowed} />
    </div>
  )
}

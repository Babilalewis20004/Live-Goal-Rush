"use client"

import { useAsync } from "@/hooks/use-async"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import type { AdPlacementOut } from "@/types/api"

/** Reserves a labelled slot where an ad may go, if (and only if) the server says this viewer is
 * eligible at this placement. There is no ad network, tracking script or identifier here: the
 * slot is an empty, clearly marked container for a future provider. Renders nothing for Premium
 * viewers, during live matches, or when ads are switched off. */
export function AdSlot({ placement, live = false }: { placement: AdPlacementOut["placement"]; live?: boolean }) {
  const { user } = useAuth()
  const { data } = useAsync(() => api.getAdPlacements(live), `ads:${live}:${user?.id ?? "anon"}`)
  const eligible = data?.find((p) => p.placement === placement)?.eligible
  if (!eligible) return null
  return (
    <aside aria-label="Advertisement" data-ad-placement={placement} className="my-4 rounded-xl border border-dashed border-white/10 px-3 py-6 text-center text-[11px] uppercase tracking-wide text-white/60">
      Advertisement
    </aside>
  )
}

"use client"

import { Star } from "lucide-react"
import { useState } from "react"

import { cn } from "@/lib/utils"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"

type FavouriteKind = "team" | "competition" | "match"

const FOLLOW: Record<FavouriteKind, (id: number) => Promise<void>> = {
  team: api.followTeam,
  competition: api.followCompetition,
  match: api.followMatch,
}

const UNFOLLOW: Record<FavouriteKind, (id: number) => Promise<void>> = {
  team: api.unfollowTeam,
  competition: api.unfollowCompetition,
  match: api.unfollowMatch,
}

/** Only rendered where the current view already knows the entity's
 * follow-state server-side (team/competition/match detail pages) --
 * deliberately not wired into every card in the live board's list views,
 * which would need a bulk follow-state lookup per row (Phase 3 §29:
 * avoid a per-row query for something a list view doesn't need). Hidden
 * entirely for anonymous visitors rather than prompting login, keeping the
 * public view untouched. */
export function FavouriteButton({
  kind,
  id,
  initialFollowed,
}: {
  kind: FavouriteKind
  id: number
  initialFollowed: boolean
}) {
  const { user } = useAuth()
  const [followed, setFollowed] = useState(initialFollowed)
  const [pending, setPending] = useState(false)

  if (!user) return null

  async function toggle() {
    if (pending) return
    setPending(true)
    const next = !followed
    setFollowed(next)
    try {
      await (next ? FOLLOW[kind](id) : UNFOLLOW[kind](id))
    } catch {
      setFollowed(!next)
    } finally {
      setPending(false)
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={pending}
      aria-pressed={followed}
      aria-label={followed ? `Unfollow this ${kind}` : `Follow this ${kind}`}
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg border transition-colors",
        followed
          ? "border-amber-400/40 bg-amber-400/10 text-amber-400"
          : "border-white/10 bg-white/[0.03] text-white/40 hover:text-white/70",
      )}
    >
      <Star className="size-4" fill={followed ? "currentColor" : "none"} />
    </button>
  )
}

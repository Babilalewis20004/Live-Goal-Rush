"use client"

import { useEffect } from "react"

import { api } from "@/lib/api"
import type { TrackEntity } from "@/types/api"

/** Counts one view of a public page. Fire-and-forget: it renders nothing, its
 * failure is invisible, and the API de-duplicates repeat visits (a refresh is
 * not a new view), so a quick double-mount can't inflate anything. */
export function TrackView({ entity, id }: { entity: TrackEntity; id: number | string }) {
  useEffect(() => {
    api.trackView(entity, id).catch(() => {})
  }, [entity, id])
  return null
}

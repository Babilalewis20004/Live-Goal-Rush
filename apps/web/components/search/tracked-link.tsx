"use client"

import Link from "next/link"
import type { ComponentProps } from "react"

import { api } from "@/lib/api"
import type { TrackEntity } from "@/types/api"

/** A search-result link that tells the API which result was chosen, so the
 * entity's "searched for" signal (trending) and the viewer's recent searches
 * are updated. Navigation never waits on, or fails because of, the tracking. */
export function TrackedLink({
  query,
  entity,
  entityId,
  ...props
}: ComponentProps<typeof Link> & { query: string; entity: TrackEntity; entityId: number }) {
  return (
    <Link
      {...props}
      onClick={(event) => {
        props.onClick?.(event)
        api.trackSearch(query, entity, entityId).catch(() => {})
      }}
    />
  )
}

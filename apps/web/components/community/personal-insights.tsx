"use client"

import Link from "next/link"

import { useAsync } from "@/hooks/use-async"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"

/** "Your followed team has a match today" and similar. Each line is a plain statement of a stored
 * fixture or result for something the viewer follows; nothing appears for people who follow nothing. */
export function PersonalInsights() {
  const { user } = useAuth()
  const { data } = useAsync(() => api.getMyInsights(), `my-insights:${user?.id ?? "anon"}`, 0, !!user)
  if (!user || !data || data.length === 0) return null
  return (
    <section aria-labelledby="my-insights" className="mb-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md">
      <h2 id="my-insights" className="text-sm font-semibold text-white">For you</h2>
      <ul className="mt-2 space-y-1.5 text-sm text-white/80">
        {data.map((i) => (
          <li key={`${i.key}-${i.entity_id}`} className="flex gap-2">
            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
            <Link href={i.entity_type === "match" ? `/match/${i.entity_id}` : `/competition/${i.entity_id}`} className="hover:underline">
              {i.text}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

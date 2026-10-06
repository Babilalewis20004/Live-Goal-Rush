"use client"

import { selectableSeasons } from "@/lib/seasons"
import type { CompetitionSeasonsOut } from "@/types/api"

/** Season picker. Stored seasons are listed first; when the provider can
 * supply history, a few earlier seasons are offered too (choosing one queues a
 * background sync and the table appears shortly). The current season is the
 * empty-string option so "back to current" restores the server-rendered data. */
export function SeasonSelect({
  info,
  value,
  onChange,
}: {
  info: CompetitionSeasonsOut | null
  value: string | null
  onChange: (season: string | null) => void
}) {
  const options = selectableSeasons(info)
  if (options.length <= 1) return null
  const current = info?.current ?? null

  return (
    <div className="mb-3 flex items-center justify-end gap-2">
      <label htmlFor="season-select" className="text-xs text-white/50">
        Season
      </label>
      <select
        id="season-select"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        className="min-h-9 rounded-lg border border-white/10 bg-[#0b0f0d] px-2 text-sm text-white"
      >
        {options.map((o) => (
          <option key={o.label} value={o.label === current ? "" : o.label}>
            {o.label}
            {o.label === current ? " (current)" : o.stored ? "" : " · load"}
          </option>
        ))}
      </select>
    </div>
  )
}

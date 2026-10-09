import type { Insight } from "@/types/api"

/** Form summaries, streaks and head-to-head, as sentences. All of it is arithmetic
 * over stored results (never a prediction), and nothing is shown when there isn't
 * enough history to say it honestly. */
export function InsightsList({ title, insights }: { title: string; insights: Insight[] }) {
  if (insights.length === 0) return null
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-white/45">{title}</h3>
      <ul className="space-y-1.5 text-sm text-white/80">
        {insights.map((i) => (
          <li key={i.key} className="flex gap-2">
            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
            <span>{i.text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

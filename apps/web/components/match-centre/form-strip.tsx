import Link from "next/link"
import { describeFormResult, formSequenceLabel } from "@/lib/match-centre"
import type { FormResult, TeamFormOut } from "@/types/api"

const TONE: Record<FormResult, string> = {
  W: "bg-emerald-500/90 text-[#04130b]",
  D: "bg-zinc-400/80 text-[#0b0f0d]",
  L: "bg-red-500/90 text-white",
}

/** Recent results as W/D/L chips, oldest on the left, latest on the right.
 * Purely historical -- it is not a prediction and is never presented as one. */
export function FormStrip({ form, title }: { form: TeamFormOut; title: string }) {
  // `results` is most-recent-first; draw oldest -> newest.
  const ordered = [...form.results].reverse()
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <h3 className="truncate text-xs font-semibold text-white/80">{title}</h3>
        <span className="text-[10px] text-white/40">
          Last {form.limit}
          {form.scope !== "overall" ? ` · ${form.scope} only` : ""}
        </span>
      </div>
      {ordered.length === 0 ? (
        <p className="text-xs text-white/40">No recent results stored.</p>
      ) : (
        <ul className="flex gap-1.5" aria-label={formSequenceLabel(form.sequence)}>
          {ordered.map((result) => (
            <li key={result.match_id}>
              <Link
                href={`/match/${result.match_id}`}
                title={describeFormResult(result)}
                aria-label={describeFormResult(result)}
                className={[
                  "flex h-7 w-7 items-center justify-center rounded-md text-xs font-bold",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400",
                  TONE[result.result],
                ].join(" ")}
              >
                <span aria-hidden="true">{result.result}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

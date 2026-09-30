import { ArrowRightLeft } from "lucide-react"
import { describeEvent, sortTimeline, type TimelineIcon, type TimelineItem } from "@/lib/match-centre"
import type { MatchDetail } from "@/types/api"

function EventIcon({ icon }: { icon: TimelineIcon }) {
  switch (icon) {
    case "yellow_card":
      return <span className="h-3.5 w-2.5 rounded-[2px] bg-amber-400" />
    case "second_yellow":
      return (
        <span className="relative h-3.5 w-3.5">
          <span className="absolute left-0 top-0 h-3.5 w-2.5 rounded-[2px] bg-amber-400" />
          <span className="absolute left-1 top-0.5 h-3.5 w-2.5 rounded-[2px] bg-red-500" />
        </span>
      )
    case "red_card":
      return <span className="h-3.5 w-2.5 rounded-[2px] bg-red-500" />
    case "substitution":
      return <ArrowRightLeft className="h-3.5 w-3.5 text-emerald-400" />
    case "var":
      return <span className="rounded bg-sky-500/20 px-1 text-[8px] font-bold text-sky-300">VAR</span>
    case "penalty_missed":
      return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-red-500/20 text-[9px] font-bold text-red-400">✕</span>
    case "own_goal":
      return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-red-500/20 text-[8px] font-bold text-red-400">OG</span>
    case "penalty":
      return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-white text-[8px] font-bold text-[#070b09]">P</span>
    case "goal":
      return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-white text-[9px] text-[#070b09]">⚽</span>
    default:
      return <span className="h-2 w-2 rounded-full bg-white/40" />
  }
}

function Entry({ item }: { item: TimelineItem }) {
  const isHome = item.side !== "away"
  const content = (
    <div className={["flex items-center gap-2", isHome ? "flex-row" : "flex-row-reverse"].join(" ")} aria-hidden="true">
      <EventIcon icon={item.icon} />
      <div className={isHome ? "min-w-0 text-left" : "min-w-0 text-right"}>
        <p className={["truncate text-xs", item.isGoal ? "font-semibold text-white" : "text-white/75"].join(" ")}>
          {item.title}
        </p>
        {item.subtitle && <p className="truncate text-[10px] text-white/45">{item.subtitle}</p>}
      </div>
    </div>
  )

  return (
    <li className="flex items-center gap-2">
      <span className="sr-only">{item.accessibleLabel}</span>
      <div className="flex-1">{item.side !== "away" && content}</div>
      <span
        aria-hidden="true"
        className="shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-white/65"
      >
        {item.minuteLabel}
      </span>
      <div className="flex-1">{item.side === "away" && content}</div>
    </li>
  )
}

/** Chronological match timeline: home events on the left, away on the right,
 * added time ordered correctly (45' → 45+2' → 46'). Everything shown comes
 * from the stored event metadata -- nothing is inferred. */
export function Timeline({ match }: { match: MatchDetail }) {
  const items = sortTimeline(match.events).map((e) => describeEvent(e, match.home_team.id, match.away_team.id))
  return (
    <section
      aria-label="Match timeline"
      className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"
    >
      <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">Timeline</h2>
      <ol className="space-y-2.5 px-4 py-4">
        {items.map((item) => (
          <Entry key={item.id} item={item} />
        ))}
      </ol>
    </section>
  )
}

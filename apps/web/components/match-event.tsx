import { ArrowRightLeft } from "lucide-react"
import type { MatchEventOut } from "@/types/api"

function EventIcon({ type }: { type: string }) {
  if (type === "yellow_card") return <span className="h-3.5 w-2.5 rounded-[2px] bg-amber-400" />
  if (type === "red_card") return <span className="h-3.5 w-2.5 rounded-[2px] bg-red-500" />
  if (type === "substitution") return <ArrowRightLeft className="h-3.5 w-3.5 text-emerald-400" />
  const isOwnGoal = type === "own_goal"
  return (
    <span
      className={[
        "flex h-4 w-4 items-center justify-center rounded-full text-[8px] font-bold",
        isOwnGoal ? "bg-red-500/20 text-red-400" : "bg-white text-[#070b09]",
      ].join(" ")}
      aria-hidden
    >
      {type === "penalty" || type === "penalty_missed" ? "P" : "⚽"}
    </span>
  )
}

export function MatchEvent({ event, isHome }: { event: MatchEventOut; isHome: boolean }) {
  const isGoal = event.event_type === "goal" || event.event_type === "penalty" || event.event_type === "own_goal"
  const detail =
    event.event_type === "substitution"
      ? event.assist_player
        ? `${event.assist_player.name} off`
        : undefined
      : event.description ?? event.assist_player?.name

  const content = (
    <div className={["flex items-center gap-2", isHome ? "flex-row" : "flex-row-reverse"].join(" ")}>
      <EventIcon type={event.event_type} />
      <div className={isHome ? "text-left" : "text-right"}>
        <p className={["text-xs", isGoal ? "font-semibold text-white" : "text-white/70"].join(" ")}>
          {event.player?.name ?? "Unknown player"}
        </p>
        {detail && <p className="text-[10px] text-white/40">{detail}</p>}
      </div>
    </div>
  )

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1">{isHome && content}</div>
      <span className="shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-white/60">
        {event.minute}
        {event.extra_minute ? `+${event.extra_minute}` : ""}&apos;
      </span>
      <div className="flex-1">{!isHome && content}</div>
    </div>
  )
}

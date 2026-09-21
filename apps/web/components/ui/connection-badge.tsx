import type { ConnectionStatus } from "@/lib/realtime"

const LABEL: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  closed: "Offline",
}

const DOT_CLASS: Record<ConnectionStatus, string> = {
  connecting: "bg-amber-400",
  open: "bg-emerald-400 ls-live-dot",
  reconnecting: "bg-amber-400 ls-live-dot",
  closed: "bg-red-400",
}

/** Surfaces the WebSocket connection state (spec §18/§29): a viewer should
 * be able to tell "reconnecting" or "offline" apart from "live and
 * current" rather than silently looking at a score that stopped moving. */
export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-medium text-white/50">
      <span className={`h-1.5 w-1.5 rounded-full ${DOT_CLASS[status]}`} />
      {LABEL[status]}
    </span>
  )
}

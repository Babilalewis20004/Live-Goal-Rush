export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-16 text-center"
    >
      <span className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-emerald-400" />
      <p className="text-sm text-white/40">{label}</p>
    </div>
  )
}

export function LoadingSkeletonRows({ count = 3 }: { count?: number }) {
  return (
    <div
      aria-hidden
      className="space-y-3 divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03]"
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex animate-pulse items-center gap-3 px-4 py-3">
          <div className="h-4 w-8 rounded bg-white/10" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-2/3 rounded bg-white/10" />
            <div className="h-3 w-1/2 rounded bg-white/10" />
          </div>
        </div>
      ))}
    </div>
  )
}

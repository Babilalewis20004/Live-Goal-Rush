"use client"

import { useRouter } from "next/navigation"

export function ErrorState({
  message = "Unable to load data.",
  onRetry,
}: {
  message?: string
  onRetry?: () => void
}) {
  const router = useRouter()
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] px-4 py-12 text-center">
      <p className="text-sm text-white/70">{message}</p>
      <button
        type="button"
        onClick={onRetry ?? (() => router.refresh())}
        className="rounded-full border border-white/10 bg-white/[0.05] px-4 py-1.5 text-xs font-medium text-white/80 transition-colors hover:bg-white/[0.1]"
      >
        Try again
      </button>
    </div>
  )
}

"use client"

import Link from "next/link"
import { useEffect, useState } from "react"

import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { EMPTY_REACTIONS, REACTIONS, applyReaction } from "@/lib/community"
import type { CommentTargetType, ReactionKind, ReactionSummary } from "@/types/api"

/** 👍 🔥 😮 ⚽ for an article or match. Counts are public; reacting needs an account.
 * One reaction per person: tapping another replaces yours, tapping yours removes it.
 * Buttons answer instantly (optimistic) and are corrected by the server's reply. */
export function ReactionsBar({ targetType, targetId }: { targetType: CommentTargetType; targetId: number }) {
  const { user, loading: authLoading } = useAuth()
  const [summary, setSummary] = useState<ReactionSummary>(EMPTY_REACTIONS)
  const [notice, setNotice] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    if (authLoading) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      try {
        const fresh = await api.getReactions(targetType, targetId)
        if (!cancelled) setSummary(fresh)
      } catch {
        // counts are decoration: leave the zeros
      }
    })()
    return () => {
      cancelled = true
    }
  }, [targetType, targetId, user?.id, authLoading])

  async function choose(kind: ReactionKind) {
    if (!user) {
      setNotice("sign-in")
      return
    }
    if (pending) return
    const before = summary
    setSummary(applyReaction(before, kind))
    setNotice(null)
    setPending(true)
    try {
      setSummary(before.mine === kind ? await api.unreact(targetType, targetId) : await api.react(targetType, targetId, kind))
    } catch (error) {
      setSummary(before)
      setNotice(error instanceof ApiError && error.status === 429 ? "Slow down a little." : "Couldn't save your reaction.")
    } finally {
      setPending(false)
    }
  }

  return (
    <div>
      <div role="group" aria-label="Reactions" className="flex flex-wrap gap-2">
        {REACTIONS.map(({ kind, emoji, label }) => {
          const count = summary.counts[kind] ?? 0
          const selected = summary.mine === kind
          return (
            <button
              key={kind}
              type="button"
              aria-pressed={selected}
              aria-label={`${label}, ${count} ${count === 1 ? "reaction" : "reactions"}${selected ? ", your reaction" : ""}`}
              onClick={() => void choose(kind)}
              className={`inline-flex min-h-10 items-center gap-1.5 rounded-full border px-3.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400 ${
                selected ? "border-emerald-400/70 bg-emerald-400/15 text-white" : "border-white/10 bg-white/[0.03] text-white/80 hover:bg-white/[0.08]"
              }`}
            >
              <span aria-hidden>{emoji}</span>
              <span className="tabular-nums">{count}</span>
              {selected && <span className="sr-only"> (selected)</span>}
            </button>
          )
        })}
      </div>
      <p role="status" aria-live="polite" className="mt-1.5 min-h-4 text-[11px] text-white/50">
        {notice === "sign-in" ? (
          <>
            <Link href="/login" className="underline hover:text-white">
              Sign in
            </Link>{" "}
            to react.
          </>
        ) : (
          notice
        )}
      </p>
    </div>
  )
}

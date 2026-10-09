"use client"

import Link from "next/link"
import { useEffect, useId, useState } from "react"

import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { leadingOption, pollClosing } from "@/lib/community"
import type { PollOut } from "@/types/api"

/** One poll. Results are always visible (counts, percentages and the leader in
 * words, so nothing depends on bar colour). Voting needs an account, is one vote
 * per person, and cannot be changed. */
export function PollCard({ poll: initial }: { poll: PollOut }) {
  const { user } = useAuth()
  const [poll, setPoll] = useState(initial)
  const [choice, setChoice] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const groupId = useId()

  // The server renders anonymous data; once we know who is looking, fetch their own vote.
  useEffect(() => {
    if (!user) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      try {
        const mine = await api.getPoll(initial.id)
        if (!cancelled) setPoll(mine)
      } catch {
        // keep what we have
      }
    })()
    return () => {
      cancelled = true
    }
  }, [user, initial.id])

  const open = poll.status === "open"
  const showResults = !open || poll.my_vote !== null
  const leader = leadingOption(poll)
  const closing = pollClosing(poll)

  async function vote() {
    if (choice === null || busy) return
    setBusy(true)
    setError(null)
    try {
      setPoll(await api.votePoll(poll.id, choice))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        try {
          setPoll(await api.getPoll(poll.id))
        } catch {
          // ignore
        }
      }
      setError(e instanceof ApiError ? e.message : "Couldn't record your vote.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby={`${groupId}-q`} className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
      <h3 id={`${groupId}-q`} className="text-sm font-semibold text-white">
        {poll.question}
      </h3>
      <p className="mt-0.5 text-[11px] text-white/45">
        {poll.total_votes} {poll.total_votes === 1 ? "vote" : "votes"}
        {closing ? ` · ${closing}` : ""}
      </p>

      {showResults ? (
        <ul className="mt-3 space-y-2">
          {poll.options.map((o) => {
            const mine = poll.my_vote === o.id
            const won = poll.winner_option_id === o.id
            return (
              <li key={o.id}>
                <div className="flex items-baseline justify-between gap-3 text-sm text-white/90">
                  <span>
                    {o.label}
                    {mine && <span className="ml-2 text-[11px] text-emerald-300">your vote</span>}
                    {won && <span className="ml-2 text-[11px] text-amber-300">winner</span>}
                  </span>
                  <span className="shrink-0 tabular-nums text-white/70">
                    {o.percent}% <span className="text-white/40">({o.votes})</span>
                  </span>
                </div>
                <div aria-hidden className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[0.08]">
                  <div className={`h-full rounded-full ${mine ? "bg-emerald-400" : "bg-white/40"}`} style={{ width: `${o.percent}%` }} />
                </div>
              </li>
            )
          })}
        </ul>
      ) : (
        <fieldset className="mt-3 space-y-1.5" disabled={!user || busy}>
          <legend className="sr-only">{poll.question}</legend>
          {poll.options.map((o) => (
            <label
              key={o.id}
              className="flex min-h-10 cursor-pointer items-center gap-3 rounded-xl border border-white/10 px-3 text-sm text-white/90 hover:bg-white/[0.05] has-[:checked]:border-emerald-400/60 has-[:checked]:bg-emerald-400/10"
            >
              <input
                type="radio"
                name={groupId}
                value={o.id}
                checked={choice === o.id}
                onChange={() => setChoice(o.id)}
                className="h-4 w-4 accent-emerald-400"
              />
              {o.label}
            </label>
          ))}
        </fieldset>
      )}

      {showResults && leader && poll.total_votes > 0 && <p className="mt-2 text-[11px] text-white/50">{open ? "Leading" : "Result"}: {leader}</p>}

      {open && poll.my_vote === null && (
        <div className="mt-3 flex items-center gap-3">
          {user ? (
            <button
              type="button"
              onClick={() => void vote()}
              disabled={choice === null || busy}
              className="min-h-10 rounded-xl bg-emerald-400 px-4 text-sm font-semibold text-[#070b09] hover:bg-emerald-300 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            >
              {busy ? "Voting…" : "Vote"}
            </button>
          ) : (
            <p className="text-xs text-white/60">
              <Link href="/login" className="underline hover:text-white">
                Sign in
              </Link>{" "}
              to vote.
            </p>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-300">
          {error}
        </p>
      )}
    </section>
  )
}

/** Polls attached to a match or article (renders nothing when there are none). */
export function PollsFor({ matchId, articleId }: { matchId?: number; articleId?: number }) {
  const [polls, setPolls] = useState<PollOut[]>([])
  useEffect(() => {
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      try {
        const found = await api.getPolls({ matchId, articleId, limit: 5 })
        if (!cancelled) setPolls(found)
      } catch {
        // polls are additive
      }
    })()
    return () => {
      cancelled = true
    }
  }, [matchId, articleId])
  if (polls.length === 0) return null
  return (
    <div className="space-y-3">
      {polls.map((p) => (
        <PollCard key={p.id} poll={p} />
      ))}
    </div>
  )
}

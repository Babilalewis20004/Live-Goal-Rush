"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"

import { PollCard } from "@/components/community/poll-card"
import { LoadingState } from "@/components/ui/loading-state"
import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { fromLocalInput } from "@/lib/editorial"
import type { PollOut } from "@/types/api"

const INPUT =
  "min-h-10 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-white placeholder:text-white/30 focus:border-emerald-400/60 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
const BTN =
  "min-h-9 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-xs text-white/80 hover:bg-white/[0.1] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

/** Create, close and delete polls (editors/admins). A match poll with no options
 * defaults to home win / draw / away win. */
export function PollManager() {
  const { user, loading: authLoading } = useAuth()
  const allowed = user?.role === "editor" || user?.role === "admin"
  const [polls, setPolls] = useState<PollOut[] | null>(null)
  const [question, setQuestion] = useState("")
  const [kind, setKind] = useState<"match" | "transfer" | "question">("question")
  const [options, setOptions] = useState("")
  const [matchId, setMatchId] = useState("")
  const [articleId, setArticleId] = useState("")
  const [closesAt, setClosesAt] = useState("")
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setPolls(await api.getPolls({ limit: 50 }))
    } catch {
      setMessage({ kind: "error", text: "Couldn't load polls." })
    }
  }, [])

  useEffect(() => {
    if (authLoading || !allowed) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      if (!cancelled) await load()
    })()
    return () => {
      cancelled = true
    }
  }, [authLoading, allowed, load])

  async function create(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      await api.createPoll({
        question: question.trim(),
        kind,
        options: options.split("\n").map((o) => o.trim()).filter(Boolean),
        match_id: matchId ? Number(matchId) : null,
        article_id: articleId ? Number(articleId) : null,
        closes_at: fromLocalInput(closesAt),
      })
      setQuestion("")
      setOptions("")
      setMatchId("")
      setArticleId("")
      setClosesAt("")
      setMessage({ kind: "ok", text: "Poll created." })
      await load()
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't create the poll." })
    } finally {
      setBusy(false)
    }
  }

  async function close(poll: PollOut) {
    try {
      await api.closePoll(poll.id)
      await load()
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't close it." })
    }
  }

  async function remove(poll: PollOut) {
    if (!window.confirm("Delete this poll and its votes?")) return
    try {
      await api.deletePoll(poll.id)
      await load()
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't delete it." })
    }
  }

  if (authLoading) return <LoadingState label="Loading…" />
  if (!allowed) return <p role="alert" className="text-sm text-white/70">Polls are managed by editors.</p>

  return (
    <div className="space-y-6">
      <Link href="/editor" className="text-xs text-white/50 hover:text-white/80">← All articles</Link>
      <h1 className="text-xl font-bold text-white">Polls</h1>

      <form onSubmit={create} className="space-y-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
        <div>
          <label htmlFor="p-q" className="block text-xs font-semibold text-white/70">Question</label>
          <input id="p-q" required minLength={5} maxLength={200} value={question} onChange={(e) => setQuestion(e.target.value)} className={INPUT} placeholder="Who will win?" />
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="p-kind" className="block text-xs font-semibold text-white/70">Type</label>
            <select id="p-kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className={INPUT}>
              <option value="question">Football question</option>
              <option value="match">Match poll</option>
              <option value="transfer">Transfer poll</option>
            </select>
          </div>
          <div>
            <label htmlFor="p-match" className="block text-xs font-semibold text-white/70">Match id (optional)</label>
            <input id="p-match" inputMode="numeric" pattern="[0-9]*" value={matchId} onChange={(e) => setMatchId(e.target.value)} className={INPUT} />
          </div>
          <div>
            <label htmlFor="p-article" className="block text-xs font-semibold text-white/70">Article id (optional)</label>
            <input id="p-article" inputMode="numeric" pattern="[0-9]*" value={articleId} onChange={(e) => setArticleId(e.target.value)} className={INPUT} />
          </div>
        </div>
        <div>
          <label htmlFor="p-options" className="block text-xs font-semibold text-white/70">Options (one per line, 2–6; leave empty for home/draw/away on a match poll)</label>
          <textarea id="p-options" rows={4} value={options} onChange={(e) => setOptions(e.target.value)} className={`${INPUT} py-2`} />
        </div>
        <div>
          <label htmlFor="p-close" className="block text-xs font-semibold text-white/70">Closes at (optional, your local time)</label>
          <input id="p-close" type="datetime-local" value={closesAt} onChange={(e) => setClosesAt(e.target.value)} className={INPUT} />
        </div>
        {message && (
          <p role={message.kind === "error" ? "alert" : "status"} className={`text-sm ${message.kind === "error" ? "text-red-300" : "text-emerald-300"}`}>
            {message.text}
          </p>
        )}
        <button type="submit" disabled={busy} className="min-h-10 rounded-xl bg-emerald-400 px-4 text-sm font-semibold text-[#070b09] hover:bg-emerald-300 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white">
          Create poll
        </button>
      </form>

      {polls === null && <LoadingState label="Loading polls…" />}
      {polls && polls.length === 0 && <p className="text-sm text-white/45">No polls yet.</p>}
      <ul className="space-y-4">
        {polls?.map((p) => (
          <li key={p.id} className="space-y-2">
            <PollCard poll={p} />
            <div className="flex gap-2">
              {p.status === "open" && <button type="button" className={BTN} onClick={() => void close(p)}>Close poll</button>}
              <button type="button" className={`${BTN} text-red-200`} onClick={() => void remove(p)}>Delete</button>
              <span className="self-center text-[11px] text-white/40">#{p.id}{p.match_id ? ` · match ${p.match_id}` : ""}{p.article_id ? ` · article ${p.article_id}` : ""}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

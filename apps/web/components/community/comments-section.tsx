"use client"

import Link from "next/link"
import { useCallback, useEffect, useId, useState } from "react"

import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { COMMENT_MAX_LENGTH, relativeTime, validateComment } from "@/lib/community"
import type { CommentOut, CommentTargetType } from "@/types/api"

const BTN =
  "inline-flex min-h-9 items-center rounded-lg px-2.5 text-xs text-white/60 hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-emerald-400"

// -- immutable tree helpers --------------------------------------------------------------

function mapComment(items: CommentOut[], id: number, fn: (c: CommentOut) => CommentOut): CommentOut[] {
  return items.map((c) => (c.id === id ? fn(c) : { ...c, replies: c.replies.map((r) => (r.id === id ? fn(r) : r)) }))
}

function removeComment(items: CommentOut[], id: number): CommentOut[] {
  return items
    .filter((c) => c.id !== id || c.replies.length > 0) // a top-level comment with replies stays as a placeholder
    .map((c) =>
      c.id === id ? { ...c, removed: true, body: "", author: null } : { ...c, replies: c.replies.filter((r) => r.id !== id) },
    )
}

function Composer({
  placeholder,
  submitLabel,
  initial = "",
  onSubmit,
  onCancel,
  autoFocus = false,
}: {
  placeholder: string
  submitLabel: string
  initial?: string
  onSubmit: (text: string) => Promise<void>
  onCancel?: () => void
  autoFocus?: boolean
}) {
  const id = useId()
  const [text, setText] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const problem = validateComment(text)
    if (problem) return setError(problem)
    setBusy(true)
    setError(null)
    try {
      await onSubmit(text.trim())
      setText("")
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't post that. Try again.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <label htmlFor={id} className="sr-only">
        {placeholder}
      </label>
      <textarea
        id={id}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        maxLength={COMMENT_MAX_LENGTH + 200}
        autoFocus={autoFocus}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-err` : undefined}
        className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-400/60 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
      />
      <div className="flex items-center justify-between gap-3">
        <span className={`text-[11px] tabular-nums ${text.length > COMMENT_MAX_LENGTH ? "text-red-300" : "text-white/40"}`}>
          {text.length}/{COMMENT_MAX_LENGTH}
        </span>
        <div className="flex gap-2">
          {onCancel && (
            <button type="button" onClick={onCancel} className={BTN}>
              Cancel
            </button>
          )}
          <button
            type="submit"
            disabled={busy || !text.trim()}
            className="min-h-9 rounded-lg bg-emerald-400 px-4 text-xs font-semibold text-[#070b09] hover:bg-emerald-300 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            {busy ? "Posting…" : submitLabel}
          </button>
        </div>
      </div>
      {error && (
        <p id={`${id}-err`} role="alert" className="text-xs text-red-300">
          {error}
        </p>
      )}
    </form>
  )
}

function CommentItem({
  comment,
  canModerate,
  signedIn,
  isReply,
  onReply,
  onChange,
  onRemove,
  onNotice,
}: {
  comment: CommentOut
  canModerate: boolean
  signedIn: boolean
  isReply: boolean
  onReply: (parentId: number, text: string) => Promise<void>
  onChange: (id: number, fn: (c: CommentOut) => CommentOut) => void
  onRemove: (id: number) => void
  onNotice: (message: string) => void
}) {
  const [mode, setMode] = useState<"view" | "reply" | "edit" | "report">("view")
  const [reason, setReason] = useState("")

  if (comment.removed) {
    return <p className="text-xs italic text-white/35">This comment was removed.</p>
  }
  const name = comment.author?.display_name ?? "Fan"

  async function toggleLike() {
    if (!signedIn) return onNotice("Sign in to like comments.")
    const wasLiked = comment.liked_by_me
    onChange(comment.id, (c) => ({ ...c, liked_by_me: !wasLiked, like_count: Math.max(0, c.like_count + (wasLiked ? -1 : 1)) }))
    try {
      const r = wasLiked ? await api.unlikeComment(comment.id) : await api.likeComment(comment.id)
      onChange(comment.id, (c) => ({ ...c, liked_by_me: r.liked_by_me, like_count: r.like_count }))
    } catch {
      onChange(comment.id, (c) => ({ ...c, liked_by_me: wasLiked, like_count: comment.like_count }))
      onNotice("Couldn't save your like.")
    }
  }

  async function remove() {
    if (!window.confirm("Delete this comment?")) return
    try {
      await api.deleteComment(comment.id)
      onRemove(comment.id)
    } catch {
      onNotice("Couldn't delete that comment.")
    }
  }

  async function report() {
    try {
      await api.reportComment(comment.id, reason)
      setMode("view")
      setReason("")
      onNotice("Thanks — a moderator will take a look.")
    } catch (e) {
      onNotice(e instanceof ApiError ? e.message : "Couldn't send your report.")
    }
  }

  return (
    <article aria-label={`Comment by ${name}`} className="text-sm">
      <header className="flex flex-wrap items-baseline gap-x-2 text-xs">
        {comment.author?.profile_public ? (
          <Link href={`/u/${comment.author.id}`} className="font-semibold text-white hover:underline">
            {name}
          </Link>
        ) : (
          <span className="font-semibold text-white">{name}</span>
        )}
        <time dateTime={comment.created_at} className="text-white/40">
          {relativeTime(comment.created_at)}
        </time>
        {comment.edited_at && <span className="text-white/30">(edited)</span>}
      </header>

      {mode === "edit" ? (
        <div className="mt-2">
          <Composer
            autoFocus
            placeholder="Edit your comment"
            submitLabel="Save"
            initial={comment.body}
            onCancel={() => setMode("view")}
            onSubmit={async (text) => {
              const updated = await api.editComment(comment.id, text)
              onChange(comment.id, (c) => ({ ...c, body: updated.body, edited_at: updated.edited_at }))
              setMode("view")
            }}
          />
        </div>
      ) : (
        // React escapes this: comment bodies are plain text, never markup.
        <p className="mt-1 whitespace-pre-wrap break-words text-white/85">{comment.body}</p>
      )}

      <div className="mt-1 flex flex-wrap items-center gap-1">
        <button type="button" onClick={() => void toggleLike()} aria-pressed={comment.liked_by_me} aria-label={`Like, ${comment.like_count} ${comment.like_count === 1 ? "like" : "likes"}`} className={`${BTN} ${comment.liked_by_me ? "text-emerald-300" : ""}`}>
          <span aria-hidden>{comment.liked_by_me ? "♥" : "♡"}</span>&nbsp;{comment.like_count}
        </button>
        {signedIn && (
          <button type="button" onClick={() => setMode(mode === "reply" ? "view" : "reply")} className={BTN}>
            Reply
          </button>
        )}
        {comment.mine && (
          <button type="button" onClick={() => setMode("edit")} className={BTN}>
            Edit
          </button>
        )}
        {(comment.mine || canModerate) && (
          <button type="button" onClick={() => void remove()} className={BTN}>
            Delete
          </button>
        )}
        {signedIn && !comment.mine && (
          <button type="button" onClick={() => setMode(mode === "report" ? "view" : "report")} className={BTN}>
            Report
          </button>
        )}
      </div>

      {mode === "reply" && (
        <div className="mt-2">
          <Composer
            autoFocus
            placeholder={`Reply to ${name}`}
            submitLabel="Reply"
            onCancel={() => setMode("view")}
            onSubmit={async (text) => {
              await onReply(comment.id, text)
              setMode("view")
            }}
          />
        </div>
      )}
      {mode === "report" && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`report-${comment.id}`}>
            Why are you reporting this comment?
          </label>
          <input
            id={`report-${comment.id}`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={200}
            placeholder="What's wrong with it? (optional)"
            className="min-h-9 flex-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 text-xs text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
          />
          <button type="button" onClick={() => void report()} className={`${BTN} border border-white/10`}>
            Send report
          </button>
        </div>
      )}
    </article>
  )
}

/** Comments for an article or match: newest/top, replies one level deep, like,
 * edit, delete, report. Anyone can read; posting needs an account. Bodies are
 * plain text. Everything the server refuses (rate limit, links on a brand-new
 * account, duplicates) is shown as the server's own message. */
export function CommentsSection({ targetType, targetId }: { targetType: CommentTargetType; targetId: number }) {
  const { user, loading: authLoading } = useAuth()
  const [sort, setSort] = useState<"newest" | "top">("newest")
  const [items, setItems] = useState<CommentOut[]>([])
  const [total, setTotal] = useState(0)
  const [totalComments, setTotalComments] = useState(0)
  const [page, setPage] = useState(1)
  const [state, setState] = useState<"loading" | "ready" | "error">("loading")
  const [more, setMore] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const headingId = useId()
  const canModerate = user?.role === "editor" || user?.role === "admin"

  const load = useCallback(
    async (pageNo: number, replace: boolean) => {
      try {
        const result = await api.getComments(targetType, targetId, { sort, page: pageNo, pageSize: 20 })
        setItems((current) => (replace ? result.items : [...current, ...result.items.filter((c) => !current.some((x) => x.id === c.id))]))
        setTotal(result.total)
        setTotalComments(result.total_comments)
        setPage(result.page)
        setState("ready")
      } catch {
        setState((s) => (s === "loading" ? "error" : s))
        setNotice("Couldn't load comments.")
      } finally {
        setMore(false)
      }
    },
    [targetType, targetId, sort],
  )

  useEffect(() => {
    if (authLoading) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      if (!cancelled) await load(1, true)
    })()
    return () => {
      cancelled = true
    }
  }, [load, user?.id, authLoading])

  async function postTop(text: string) {
    const created = await api.postComment(targetType, targetId, text)
    setItems((current) => [created, ...current])
    setTotal((n) => n + 1)
    setTotalComments((n) => n + 1)
  }

  async function postReply(parentId: number, text: string) {
    const created = await api.postComment(targetType, targetId, text, parentId)
    setItems((current) => {
      const top = current.find((c) => c.id === parentId || c.replies.some((r) => r.id === parentId))
      return top ? mapComment(current, top.id, (c) => ({ ...c, replies: [...c.replies, created], reply_count: c.reply_count + 1 })) : current
    })
    setTotalComments((n) => n + 1)
  }

  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 id={headingId} className="text-sm font-semibold text-white">
          Comments <span className="font-normal text-white/40">({totalComments})</span>
        </h2>
        <div role="group" aria-label="Sort comments" className="flex gap-1 text-xs">
          {(["newest", "top"] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={sort === s}
              onClick={() => {
                setState("loading")
                setSort(s)
              }}
              className={`min-h-9 rounded-lg px-3 ${sort === s ? "bg-white/[0.1] text-white" : "text-white/55 hover:bg-white/[0.06]"} focus-visible:outline-2 focus-visible:outline-emerald-400`}
            >
              {s === "newest" ? "Newest" : "Top"}
            </button>
          ))}
        </div>
      </div>

      {user ? (
        <Composer placeholder="Add a comment" submitLabel="Post" onSubmit={postTop} />
      ) : (
        <p className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-sm text-white/60">
          <Link href="/login" className="underline hover:text-white">
            Sign in
          </Link>{" "}
          to join the conversation.
        </p>
      )}

      <p role="status" aria-live="polite" className="min-h-4 text-xs text-white/60">
        {notice}
      </p>

      {state === "loading" && <p className="text-sm text-white/40">Loading comments…</p>}
      {state === "error" && (
        <button type="button" onClick={() => void load(1, true)} className={`${BTN} border border-white/10`}>
          Try again
        </button>
      )}
      {state === "ready" && items.length === 0 && <p className="text-sm text-white/40">No comments yet. Be the first.</p>}

      <ul className="space-y-5">
        {items.map((c) => (
          <li key={c.id}>
            <CommentItem
              comment={c}
              canModerate={canModerate}
              signedIn={!!user}
              isReply={false}
              onReply={postReply}
              onChange={(id, fn) => setItems((current) => mapComment(current, id, fn))}
              onRemove={(id) => {
                setItems((current) => removeComment(current, id))
                setTotalComments((n) => Math.max(0, n - 1))
              }}
              onNotice={setNotice}
            />
            {c.replies.length > 0 && (
              <ul className="mt-3 space-y-4 border-l border-white/[0.08] pl-4">
                {c.replies.map((r) => (
                  <li key={r.id}>
                    <CommentItem
                      comment={r}
                      canModerate={canModerate}
                      signedIn={!!user}
                      isReply
                      onReply={(_parent, text) => postReply(c.id, text)}
                      onChange={(id, fn) => setItems((current) => mapComment(current, id, fn))}
                      onRemove={(id) => {
                        setItems((current) => removeComment(current, id))
                        setTotalComments((n) => Math.max(0, n - 1))
                      }}
                      onNotice={setNotice}
                    />
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {items.length < total && (
        <button
          type="button"
          disabled={more}
          onClick={() => {
            setMore(true)
            void load(page + 1, false)
          }}
          className="min-h-10 w-full rounded-xl border border-white/10 bg-white/[0.03] text-xs font-medium text-white/80 hover:bg-white/[0.07] disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
        >
          {more ? "Loading…" : `Load more comments (${total - items.length})`}
        </button>
      )}
    </section>
  )
}

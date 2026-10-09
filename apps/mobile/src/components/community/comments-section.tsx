import { Link } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native"

import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { COMMENT_MAX_LENGTH, relativeTime, validateComment } from "@/lib/community"
import { theme } from "@/theme"
import type { CommentOut, CommentTargetType } from "@/types/api"

// -- immutable tree helpers (same as web) ---------------------------------------------------

function mapComment(items: CommentOut[], id: number, fn: (c: CommentOut) => CommentOut): CommentOut[] {
  return items.map((c) => (c.id === id ? fn(c) : { ...c, replies: c.replies.map((r) => (r.id === id ? fn(r) : r)) }))
}

function removeComment(items: CommentOut[], id: number): CommentOut[] {
  return items
    .filter((c) => c.id !== id || c.replies.length > 0)
    .map((c) => (c.id === id ? { ...c, removed: true, body: "", author: null } : { ...c, replies: c.replies.filter((r) => r.id !== id) }))
}

function Composer({
  label,
  submitLabel,
  initial = "",
  onSubmit,
  onCancel,
}: {
  label: string
  submitLabel: string
  initial?: string
  onSubmit: (text: string) => Promise<void>
  onCancel?: () => void
}) {
  const [text, setText] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit() {
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
    <View style={{ gap: 6 }}>
      <TextInput
        accessibilityLabel={label}
        placeholder={label}
        placeholderTextColor={theme.textFaint}
        value={text}
        onChangeText={setText}
        multiline
        maxLength={COMMENT_MAX_LENGTH + 200}
        style={styles.input}
      />
      <View style={styles.composerFooter}>
        <Text style={[styles.counter, text.length > COMMENT_MAX_LENGTH && { color: "#fca5a5" }]}>
          {text.length}/{COMMENT_MAX_LENGTH}
        </Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          {onCancel ? (
            <Pressable accessibilityRole="button" onPress={onCancel} style={styles.ghost}>
              <Text style={styles.ghostText}>Cancel</Text>
            </Pressable>
          ) : null}
          <Pressable
            accessibilityRole="button"
            disabled={busy || !text.trim()}
            onPress={() => void submit()}
            style={[styles.post, (busy || !text.trim()) && { opacity: 0.5 }]}
          >
            <Text style={styles.postText}>{busy ? "Posting…" : submitLabel}</Text>
          </Pressable>
        </View>
      </View>
      {error ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      ) : null}
    </View>
  )
}

function CommentItem({
  comment,
  canModerate,
  signedIn,
  onReply,
  onChange,
  onRemove,
  onNotice,
}: {
  comment: CommentOut
  canModerate: boolean
  signedIn: boolean
  onReply: (text: string) => Promise<void>
  onChange: (id: number, fn: (c: CommentOut) => CommentOut) => void
  onRemove: (id: number) => void
  onNotice: (message: string) => void
}) {
  const [mode, setMode] = useState<"view" | "reply" | "edit" | "report" | "confirm-delete">("view")
  const [reason, setReason] = useState("")

  if (comment.removed) return <Text style={styles.removed}>This comment was removed.</Text>
  const name = comment.author?.display_name ?? "Fan"

  async function toggleLike() {
    if (!signedIn) return onNotice("Sign in to like comments.")
    const wasLiked = comment.liked_by_me
    const before = comment.like_count
    onChange(comment.id, (c) => ({ ...c, liked_by_me: !wasLiked, like_count: Math.max(0, c.like_count + (wasLiked ? -1 : 1)) }))
    try {
      const r = wasLiked ? await api.unlikeComment(comment.id) : await api.likeComment(comment.id)
      onChange(comment.id, (c) => ({ ...c, liked_by_me: r.liked_by_me, like_count: r.like_count }))
    } catch {
      onChange(comment.id, (c) => ({ ...c, liked_by_me: wasLiked, like_count: before }))
      onNotice("Couldn't save your like.")
    }
  }

  async function remove() {
    try {
      await api.deleteComment(comment.id)
      onRemove(comment.id)
    } catch {
      onNotice("Couldn't delete that comment.")
      setMode("view")
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

  const action = (label: string, onPress: () => void, extra?: object) => (
    <Pressable accessibilityRole="button" accessibilityLabel={`${label} comment by ${name}`} onPress={onPress} style={styles.action} {...extra}>
      <Text style={styles.actionText}>{label}</Text>
    </Pressable>
  )

  return (
    <View accessibilityLabel={`Comment by ${name}`}>
      <Text style={styles.meta}>
        {comment.author?.profile_public ? (
          <Link href={{ pathname: "/u/[id]", params: { id: String(comment.author.id) } }} style={styles.name}>
            {name}
          </Link>
        ) : (
          <Text style={styles.name}>{name}</Text>
        )}
        {"  "}
        {relativeTime(comment.created_at)}
        {comment.edited_at ? "  (edited)" : ""}
      </Text>

      {mode === "edit" ? (
        <Composer
          label="Edit your comment"
          submitLabel="Save"
          initial={comment.body}
          onCancel={() => setMode("view")}
          onSubmit={async (text) => {
            const updated = await api.editComment(comment.id, text)
            onChange(comment.id, (c) => ({ ...c, body: updated.body, edited_at: updated.edited_at }))
            setMode("view")
          }}
        />
      ) : (
        // Rendered as text: a comment body is never interpreted as markup.
        <Text style={styles.body}>{comment.body}</Text>
      )}

      <View style={styles.actions}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ selected: comment.liked_by_me }}
          accessibilityLabel={`Like comment by ${name}, ${comment.like_count} ${comment.like_count === 1 ? "like" : "likes"}`}
          onPress={() => void toggleLike()}
          style={styles.action}
        >
          <Text style={[styles.actionText, comment.liked_by_me && { color: theme.emerald }]}>
            {comment.liked_by_me ? "♥" : "♡"} {comment.like_count}
          </Text>
        </Pressable>
        {signedIn ? action("Reply", () => setMode(mode === "reply" ? "view" : "reply")) : null}
        {comment.mine ? action("Edit", () => setMode("edit")) : null}
        {comment.mine || canModerate ? action("Delete", () => setMode("confirm-delete")) : null}
        {signedIn && !comment.mine ? action("Report", () => setMode(mode === "report" ? "view" : "report")) : null}
      </View>

      {mode === "confirm-delete" ? (
        <View style={styles.inline}>
          <Text style={styles.actionText}>Delete this comment?</Text>
          <Pressable accessibilityRole="button" onPress={() => void remove()} style={styles.action}>
            <Text style={[styles.actionText, { color: "#fca5a5" }]}>Yes, delete</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onPress={() => setMode("view")} style={styles.action}>
            <Text style={styles.actionText}>Keep</Text>
          </Pressable>
        </View>
      ) : null}
      {mode === "reply" ? (
        <Composer
          label={`Reply to ${name}`}
          submitLabel="Reply"
          onCancel={() => setMode("view")}
          onSubmit={async (text) => {
            await onReply(text)
            setMode("view")
          }}
        />
      ) : null}
      {mode === "report" ? (
        <View style={styles.inline}>
          <TextInput
            accessibilityLabel="Why are you reporting this comment?"
            placeholder="What's wrong with it? (optional)"
            placeholderTextColor={theme.textFaint}
            value={reason}
            onChangeText={setReason}
            maxLength={200}
            style={[styles.input, { flex: 1, minHeight: 40 }]}
          />
          <Pressable accessibilityRole="button" onPress={() => void report()} style={styles.action}>
            <Text style={styles.actionText}>Send</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  )
}

/** Comments for an article or match: newest/top, replies one level deep, like,
 * edit, delete, report. Reading is open; posting needs an account. */
export function CommentsSection({ targetType, targetId }: { targetType: CommentTargetType; targetId: number }) {
  const { user, loading: authLoading } = useAuth()
  const [sort, setSort] = useState<"newest" | "top">("newest")
  const [items, setItems] = useState<CommentOut[]>([])
  const [total, setTotal] = useState(0)
  const [totalComments, setTotalComments] = useState(0)
  const [page, setPage] = useState(1)
  const [state, setState] = useState<"loading" | "ready" | "error">("loading")
  const [moreBusy, setMoreBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
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
        setMoreBusy(false)
      }
    },
    [targetType, targetId, sort],
  )

  useEffect(() => {
    if (authLoading) return
    let cancelled = false
    const handle = setTimeout(() => {
      if (!cancelled) void load(1, true)
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [load, user?.id, authLoading])

  async function postTop(text: string) {
    const created = await api.postComment(targetType, targetId, text)
    setItems((current) => [created, ...current])
    setTotal((n) => n + 1)
    setTotalComments((n) => n + 1)
  }

  async function postReply(topId: number, text: string) {
    const created = await api.postComment(targetType, targetId, text, topId)
    setItems((current) => mapComment(current, topId, (c) => ({ ...c, replies: [...c.replies, created], reply_count: c.reply_count + 1 })))
    setTotalComments((n) => n + 1)
  }

  const removeFrom = (id: number) => {
    setItems((current) => removeComment(current, id))
    setTotalComments((n) => Math.max(0, n - 1))
  }

  return (
    <View style={{ gap: 12 }}>
      <View style={styles.headRow}>
        <Text accessibilityRole="header" style={styles.heading}>
          Comments <Text style={styles.meta}>({totalComments})</Text>
        </Text>
        <View style={{ flexDirection: "row", gap: 4 }}>
          {(["newest", "top"] as const).map((s) => (
            <Pressable
              key={s}
              accessibilityRole="button"
              accessibilityState={{ selected: sort === s }}
              onPress={() => {
                setState("loading")
                setSort(s)
              }}
              style={[styles.sort, sort === s && styles.sortOn]}
            >
              <Text style={[styles.actionText, sort === s && { color: theme.text }]}>{s === "newest" ? "Newest" : "Top"}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {user ? (
        <Composer label="Add a comment" submitLabel="Post" onSubmit={postTop} />
      ) : (
        <Text style={styles.signIn}>
          <Link href="/login" style={styles.link}>
            Sign in
          </Link>{" "}
          to join the conversation.
        </Text>
      )}

      {notice ? (
        <Text accessibilityLiveRegion="polite" style={styles.meta}>
          {notice}
        </Text>
      ) : null}
      {state === "loading" ? <Text style={styles.meta}>Loading comments…</Text> : null}
      {state === "error" ? (
        <Pressable accessibilityRole="button" onPress={() => void load(1, true)} style={styles.ghost}>
          <Text style={styles.ghostText}>Try again</Text>
        </Pressable>
      ) : null}
      {state === "ready" && items.length === 0 ? <Text style={styles.meta}>No comments yet. Be the first.</Text> : null}

      {items.map((c) => (
        <View key={c.id} style={{ gap: 10 }}>
          <CommentItem
            comment={c}
            canModerate={canModerate}
            signedIn={!!user}
            onReply={(text) => postReply(c.id, text)}
            onChange={(id, fn) => setItems((current) => mapComment(current, id, fn))}
            onRemove={removeFrom}
            onNotice={setNotice}
          />
          {c.replies.length > 0 ? (
            <View style={styles.replies}>
              {c.replies.map((r) => (
                <CommentItem
                  key={r.id}
                  comment={r}
                  canModerate={canModerate}
                  signedIn={!!user}
                  onReply={(text) => postReply(c.id, text)}
                  onChange={(id, fn) => setItems((current) => mapComment(current, id, fn))}
                  onRemove={removeFrom}
                  onNotice={setNotice}
                />
              ))}
            </View>
          ) : null}
        </View>
      ))}

      {items.length < total ? (
        <Pressable
          accessibilityRole="button"
          disabled={moreBusy}
          onPress={() => {
            setMoreBusy(true)
            void load(page + 1, false)
          }}
          style={styles.more}
        >
          <Text style={styles.ghostText}>{moreBusy ? "Loading…" : `Load more comments (${total - items.length})`}</Text>
        </Pressable>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  headRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  heading: { color: theme.text, fontSize: 15, fontWeight: "700" },
  meta: { color: theme.textFaint, fontSize: 12 },
  name: { color: theme.text, fontWeight: "700", fontSize: 13 },
  body: { color: "rgba(255,255,255,0.88)", fontSize: 14, lineHeight: 20, marginTop: 4 },
  removed: { color: theme.textFaint, fontStyle: "italic", fontSize: 12 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 2, marginTop: 4, marginLeft: -8 },
  action: { minHeight: 36, minWidth: 40, paddingHorizontal: 8, alignItems: "center", justifyContent: "center", borderRadius: 8 },
  actionText: { color: theme.textMuted, fontSize: 12 },
  inline: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 },
  replies: { marginLeft: 10, paddingLeft: 12, borderLeftWidth: StyleSheet.hairlineWidth, borderLeftColor: theme.border, gap: 12 },
  input: {
    minHeight: 72,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    color: theme.text,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 14,
    textAlignVertical: "top",
  },
  composerFooter: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  counter: { color: theme.textFaint, fontSize: 11 },
  post: { minHeight: 40, paddingHorizontal: 16, borderRadius: 10, backgroundColor: theme.emerald, alignItems: "center", justifyContent: "center" },
  postText: { color: theme.background, fontWeight: "700", fontSize: 13 },
  ghost: { minHeight: 40, paddingHorizontal: 14, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  ghostText: { color: theme.textMuted, fontSize: 13 },
  more: { minHeight: 44, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card, alignItems: "center", justifyContent: "center" },
  sort: { minHeight: 36, paddingHorizontal: 12, justifyContent: "center", borderRadius: 8 },
  sortOn: { backgroundColor: "rgba(255,255,255,0.1)" },
  signIn: { color: theme.textMuted, fontSize: 13, padding: 12, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border },
  link: { color: theme.emerald, textDecorationLine: "underline" },
  error: { color: "#fca5a5", fontSize: 12 },
})

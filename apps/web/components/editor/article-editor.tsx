"use client"

import Image from "next/image"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useState } from "react"

import { EntityPicker } from "@/components/editor/entity-picker"
import { MediaLibrary } from "@/components/editor/media-library"
import { RevisionsPanel } from "@/components/editor/revisions-panel"
import { ArticleBody } from "@/components/news/article-body"
import { LoadingState } from "@/components/ui/loading-state"
import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import {
  EMPTY_FIELDS,
  STATUS_LABEL,
  buildInput,
  fieldsFromArticle,
  validateFields,
  validatePublish,
  type EditorFields,
} from "@/lib/editor"
import { STATUS_HELP, availableActions, fromLocalInput, validateSchedule, type EditorialAction, type StaffRole } from "@/lib/editorial"
import type { ArticleAdminOut, ArticleStatus, CategoryOut, MediaOut } from "@/types/api"

const INPUT =
  "min-h-10 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-white placeholder:text-white/30 focus:border-emerald-400/60 focus:outline-none focus:ring-2 focus:ring-emerald-400/30 disabled:opacity-60"
const BTN =
  "min-h-10 rounded-xl border border-white/10 bg-white/[0.05] px-4 text-sm font-medium text-white/85 hover:bg-white/[0.1] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
const PRIMARY =
  "min-h-10 rounded-xl bg-emerald-400 px-4 text-sm font-semibold text-[#070b09] hover:bg-emerald-300 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"

type Tab = "edit" | "preview" | "history"

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-semibold text-white/70">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-white/35">{hint}</p>}
    </div>
  )
}

/** Create or edit one article. What each person can do follows the editorial
 * workflow: authors write drafts and submit them; editors review, schedule and
 * publish. The buttons shown come from `availableActions` (mirroring the server's
 * rules); the API enforces them regardless, so this is guidance, not security. */
export function ArticleEditor({ articleId }: { articleId?: number }) {
  const router = useRouter()
  const { user, loading: authLoading } = useAuth()
  const [fields, setFields] = useState<EditorFields>(EMPTY_FIELDS)
  const [article, setArticle] = useState<ArticleAdminOut | null>(null)
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [loading, setLoading] = useState(articleId !== undefined)
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<Tab>("edit")
  const [picker, setPicker] = useState<"featured" | "gallery" | null>(null)
  const [rejectNote, setRejectNote] = useState("")
  const [rejecting, setRejecting] = useState(false)
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null)

  const role = user && (user.role === "author" || user.role === "editor" || user.role === "admin") ? (user.role as StaffRole) : null
  const reviewer = role === "editor" || role === "admin"

  const load = useCallback(async () => {
    try {
      const [cats, existing] = await Promise.all([
        api.getEditorCategories(),
        articleId !== undefined ? api.getEditorArticle(articleId) : Promise.resolve(null),
      ])
      setCategories(cats)
      if (existing) {
        setArticle(existing)
        setFields(fieldsFromArticle(existing))
      }
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof ApiError ? error.message : "Couldn't load the article." })
    } finally {
      setLoading(false)
    }
  }, [articleId])

  useEffect(() => {
    if (authLoading || !role) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      if (!cancelled) await load()
    })()
    return () => {
      cancelled = true
    }
  }, [authLoading, role, load])

  if (authLoading || (role && loading)) return <LoadingState label="Loading editor…" />
  if (!role || !user) {
    return (
      <div role="alert" className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-6 text-sm text-white/70">
        You need a writer or editor account to use this area. <Link href="/" className="underline">Back to livescores</Link>
      </div>
    )
  }

  const status: ArticleStatus = article?.status ?? "draft"
  const isOwner = !article || article.author_id === user.id
  const actions = availableActions(role, status, isOwner)
  const canWrite = actions.includes("save")
  const set = <K extends keyof EditorFields>(key: K, value: EditorFields[K]) => setFields((f) => ({ ...f, [key]: value }))
  const input = () => buildInput(fields, { includeSchedule: reviewer })

  function adopt(saved: ArticleAdminOut, success: string) {
    setArticle(saved)
    setFields(fieldsFromArticle(saved))
    setMessage({ kind: "ok", text: success })
    if (articleId === undefined) router.replace(`/editor/${saved.id}`)
  }

  async function run(action: () => Promise<ArticleAdminOut | null>, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      const saved = await action()
      if (saved) adopt(saved, success)
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof ApiError ? error.message : "Something went wrong. Nothing was lost — try again." })
    } finally {
      setBusy(false)
    }
  }

  /** Save pending edits first (when allowed) so a workflow step never acts on a stale version. */
  async function saved(): Promise<ArticleAdminOut> {
    if (!canWrite && article) return article
    return article ? api.updateArticle(article.id, input()) : api.createArticle(input())
  }

  function save() {
    const problem = validateFields(fields)
    if (problem) return setMessage({ kind: "error", text: problem })
    void run(async () => (article ? api.updateArticle(article.id, input()) : api.createArticle(input())), "Saved.")
  }

  function act(action: EditorialAction) {
    if (action === "publish" || action === "approve" || action === "submit" || action === "schedule") {
      const problem = validatePublish(fields)
      if (problem) return setMessage({ kind: "error", text: problem })
    }
    if (action === "schedule") {
      const problem = validateSchedule(fields.publishAt, fields.unpublishAt)
      if (problem) return setMessage({ kind: "error", text: problem })
    }
    const publishAt = fromLocalInput(fields.publishAt)
    const unpublishAt = fromLocalInput(fields.unpublishAt)
    const flows: Partial<Record<EditorialAction, [() => Promise<ArticleAdminOut>, string]>> = {
      submit: [async () => api.submitArticle((await saved()).id), "Submitted for review."],
      withdraw: [async () => api.withdrawArticle((await saved()).id), "Withdrawn. You can edit it again."],
      approve: [
        async () => {
          const s = await saved()
          return api.approveArticle(s.id, publishAt ? { publish_at: publishAt, unpublish_at: unpublishAt ?? undefined } : unpublishAt ? { unpublish_at: unpublishAt } : {})
        },
        publishAt ? "Approved and scheduled." : "Approved and published.",
      ],
      publish: [async () => api.setArticleStatus((await saved()).id, "publish"), "Published."],
      schedule: [async () => api.scheduleArticle((await saved()).id, publishAt!, unpublishAt ?? undefined), "Scheduled."],
      unpublish: [async () => api.setArticleStatus((await saved()).id, "unpublish"), "Moved back to draft."],
      archive: [async () => api.setArticleStatus((await saved()).id, "archive"), "Archived."],
    }
    const flow = flows[action]
    if (flow) void run(flow[0], flow[1])
  }

  async function reject() {
    if (!article) return
    await run(() => api.rejectArticle(article.id, rejectNote.trim()), "Sent back to the author.")
    setRejecting(false)
    setRejectNote("")
  }

  async function remove() {
    if (!article || !window.confirm("Delete this article permanently?")) return
    setBusy(true)
    try {
      await api.deleteArticle(article.id)
      router.replace("/editor")
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof ApiError ? error.message : "Couldn't delete the article." })
      setBusy(false)
    }
  }

  function useFeatured(media: MediaOut) {
    setFields((f) => ({ ...f, featuredMedia: { id: media.id, url: media.url }, imageUrl: "", imageAlt: f.imageAlt || media.alt_text }))
    setPicker(null)
  }

  function addToGallery(media: MediaOut) {
    setFields((f) =>
      f.gallery.some((g) => g.media_id === media.id)
        ? f
        : { ...f, gallery: [...f.gallery, { media_id: media.id, caption: "", thumb_url: media.thumb_url, alt: media.alt_text || media.filename }] },
    )
  }

  function moveGallery(index: number, delta: -1 | 1) {
    setFields((f) => {
      const next = [...f.gallery]
      const target = index + delta
      if (target < 0 || target >= next.length) return f
      ;[next[index], next[target]] = [next[target], next[index]]
      return { ...f, gallery: next }
    })
  }

  const show = (a: EditorialAction) => actions.includes(a)
  const tabs: { id: Tab; label: string }[] = [
    { id: "edit", label: "Edit" },
    { id: "preview", label: "Preview" },
    ...(article ? [{ id: "history" as const, label: "History" }] : []),
  ]

  return (
    <div className="space-y-5" aria-busy={busy}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href="/editor" className="text-xs text-white/50 hover:text-white/80">
          ← All articles
        </Link>
        {article && status === "published" && (
          <Link href={`/article/${article.slug}`} className="text-xs text-white/60 underline hover:text-white">
            View live
          </Link>
        )}
      </div>

      <div>
        <h1 className="text-xl font-bold text-white">{article ? "Edit article" : "New article"}</h1>
        <p className="mt-1 text-xs text-white/55">
          Status: <strong className="text-white/85">{STATUS_LABEL[status]}</strong> — {STATUS_HELP[status]}
          {status === "scheduled" && article?.publish_at && <> Goes live {new Date(article.publish_at).toLocaleString()}.</>}
        </p>
      </div>

      {article?.review_note && status === "draft" && (
        <div role="note" className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          <strong>Changes requested:</strong> {article.review_note}
        </div>
      )}
      {!canWrite && article && (
        <p role="note" className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-white/65">
          You can read this article but not change it in its current state.
        </p>
      )}

      <div role="tablist" aria-label="Editor sections" className="flex gap-1 rounded-xl border border-white/[0.08] bg-white/[0.03] p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`min-h-9 flex-1 rounded-lg text-xs font-semibold focus-visible:outline-2 focus-visible:outline-emerald-400 ${tab === t.id ? "bg-white/[0.1] text-white" : "text-white/55 hover:bg-white/[0.05]"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "edit" && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            save()
          }}
          className="space-y-5"
        >
          <fieldset disabled={!canWrite || busy} className="space-y-5 border-0 p-0">
            <Field id="a-title" label="Headline">
              <input id="a-title" required minLength={3} maxLength={200} value={fields.title} onChange={(e) => set("title", e.target.value)} className={INPUT} />
            </Field>
            <Field id="a-excerpt" label="Summary" hint="Shown on cards and in search results. Leave blank to use the start of the article.">
              <textarea id="a-excerpt" rows={2} maxLength={500} value={fields.excerpt} onChange={(e) => set("excerpt", e.target.value)} className={`${INPUT} py-2`} />
            </Field>
            <Field
              id="a-content"
              label="Article body (HTML)"
              hint="Allowed: headings (h2–h4), paragraphs, bold, italic, lists, quotes, links and images. Anything else — scripts, styles, event handlers — is removed when you save."
            >
              <textarea id="a-content" rows={14} value={fields.content} onChange={(e) => set("content", e.target.value)} className={`${INPUT} py-2 font-mono text-[13px]`} />
            </Field>

            <div className="space-y-3 rounded-2xl border border-white/[0.08] p-4">
              <h2 className="text-sm font-semibold text-white">Featured image</h2>
              {fields.featuredMedia ? (
                <div className="flex items-center gap-3">
                  <div className="relative h-20 w-32 overflow-hidden rounded-lg bg-white/[0.04]">
                    <Image src={fields.featuredMedia.url} alt="" fill sizes="128px" className="object-cover" unoptimized />
                  </div>
                  <button type="button" className={BTN} onClick={() => set("featuredMedia", null)}>
                    Remove
                  </button>
                </div>
              ) : (
                <Field id="a-image" label="Or use an image address" hint="An http(s) link to an image on another site.">
                  <input id="a-image" type="url" inputMode="url" maxLength={512} value={fields.imageUrl} onChange={(e) => set("imageUrl", e.target.value)} className={INPUT} placeholder="https://…" />
                </Field>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className={BTN} aria-expanded={picker === "featured"} onClick={() => setPicker(picker === "featured" ? null : "featured")}>
                  {picker === "featured" ? "Close library" : "Choose or upload an image"}
                </button>
              </div>
              {picker === "featured" && <MediaLibrary mode="pick" onPick={useFeatured} />}
              <Field id="a-alt" label="Image description" hint="For screen readers. Defaults to the headline.">
                <input id="a-alt" maxLength={200} value={fields.imageAlt} onChange={(e) => set("imageAlt", e.target.value)} className={INPUT} disabled={!fields.featuredMedia && !fields.imageUrl.trim()} />
              </Field>
            </div>

            <div className="space-y-3 rounded-2xl border border-white/[0.08] p-4">
              <h2 className="text-sm font-semibold text-white">Gallery</h2>
              {fields.gallery.length === 0 && <p className="text-xs text-white/40">No gallery images.</p>}
              <ul className="space-y-2">
                {fields.gallery.map((g, i) => (
                  <li key={g.media_id} className="flex items-center gap-3 rounded-xl bg-white/[0.03] p-2">
                    <div className="relative h-14 w-20 shrink-0 overflow-hidden rounded-md bg-white/[0.04]">
                      <Image src={g.thumb_url} alt={g.alt} fill sizes="80px" className="object-cover" unoptimized />
                    </div>
                    <label className="sr-only" htmlFor={`cap-${g.media_id}`}>
                      Caption for {g.alt}
                    </label>
                    <input
                      id={`cap-${g.media_id}`}
                      value={g.caption}
                      maxLength={200}
                      placeholder="Caption"
                      onChange={(e) => setFields((f) => ({ ...f, gallery: f.gallery.map((x) => (x.media_id === g.media_id ? { ...x, caption: e.target.value } : x)) }))}
                      className="min-h-9 min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.03] px-2 text-xs text-white"
                    />
                    <button type="button" aria-label={`Move ${g.alt} up`} disabled={i === 0} className={BTN} onClick={() => moveGallery(i, -1)}>
                      ↑
                    </button>
                    <button type="button" aria-label={`Move ${g.alt} down`} disabled={i === fields.gallery.length - 1} className={BTN} onClick={() => moveGallery(i, 1)}>
                      ↓
                    </button>
                    <button type="button" aria-label={`Remove ${g.alt} from the gallery`} className={BTN} onClick={() => setFields((f) => ({ ...f, gallery: f.gallery.filter((x) => x.media_id !== g.media_id) }))}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
              <button type="button" className={BTN} aria-expanded={picker === "gallery"} onClick={() => setPicker(picker === "gallery" ? null : "gallery")}>
                {picker === "gallery" ? "Close library" : "Add gallery images"}
              </button>
              {picker === "gallery" && <MediaLibrary mode="pick" onPick={addToGallery} />}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="a-category" label="Category">
                <select id="a-category" value={fields.categoryId ?? ""} onChange={(e) => set("categoryId", e.target.value ? Number(e.target.value) : null)} className={INPUT}>
                  <option value="">No category</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="a-tags" label="Tags" hint="Comma separated, up to 10. Existing tags are reused.">
                <input id="a-tags" value={fields.tags} onChange={(e) => set("tags", e.target.value)} className={INPUT} placeholder="Transfer, Injury, Real Madrid" />
              </Field>
            </div>

            {reviewer && (
              <>
                <label className="flex items-center gap-2 text-sm text-white/80">
                  <input type="checkbox" checked={fields.featured} onChange={(e) => set("featured", e.target.checked)} className="h-4 w-4 accent-emerald-400" />
                  Feature on the home page (and eligible for general-news notifications)
                </label>
                <div className="grid gap-4 rounded-2xl border border-white/[0.08] p-4 sm:grid-cols-2">
                  <Field id="a-publish-at" label="Publish at (your local time)" hint="Used by Schedule and by Approve.">
                    <input id="a-publish-at" type="datetime-local" value={fields.publishAt} onChange={(e) => set("publishAt", e.target.value)} className={INPUT} />
                  </Field>
                  <Field id="a-unpublish-at" label="Archive automatically at (optional)" hint="Takes the article down by itself.">
                    <input id="a-unpublish-at" type="datetime-local" value={fields.unpublishAt} onChange={(e) => set("unpublishAt", e.target.value)} className={INPUT} />
                  </Field>
                </div>
              </>
            )}

            <EntityPicker value={fields.entities} onChange={(entities) => set("entities", entities)} />
          </fieldset>

          {message && (
            <p
              role={message.kind === "error" ? "alert" : "status"}
              className={`rounded-xl px-4 py-3 text-sm ${message.kind === "error" ? "border border-red-500/30 bg-red-500/10 text-red-200" : "border border-emerald-400/30 bg-emerald-400/10 text-emerald-100"}`}
            >
              {message.text}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {show("save") && (
              <button type="submit" disabled={busy} className={BTN}>
                {article ? "Save changes" : "Save draft"}
              </button>
            )}
            {show("submit") && (
              <button type="button" disabled={busy} onClick={() => act("submit")} className={reviewer ? BTN : PRIMARY}>
                Submit for review
              </button>
            )}
            {show("withdraw") && (
              <button type="button" disabled={busy} onClick={() => act("withdraw")} className={BTN}>
                {reviewer ? "Back to draft" : "Withdraw from review"}
              </button>
            )}
            {show("approve") && (
              <button type="button" disabled={busy} onClick={() => act("approve")} className={PRIMARY}>
                {fields.publishAt ? "Approve & schedule" : "Approve & publish"}
              </button>
            )}
            {show("reject") && (
              <button type="button" disabled={busy} onClick={() => setRejecting((v) => !v)} aria-expanded={rejecting} className={BTN}>
                Request changes
              </button>
            )}
            {show("publish") && (
              <button type="button" disabled={busy} onClick={() => act("publish")} className={PRIMARY}>
                Publish now
              </button>
            )}
            {show("schedule") && (
              <button type="button" disabled={busy} onClick={() => act("schedule")} className={BTN}>
                Schedule
              </button>
            )}
            {show("unpublish") && (
              <button type="button" disabled={busy} onClick={() => act("unpublish")} className={BTN}>
                {status === "scheduled" ? "Cancel schedule" : "Unpublish"}
              </button>
            )}
            {show("archive") && (
              <button type="button" disabled={busy} onClick={() => act("archive")} className={BTN}>
                Archive
              </button>
            )}
            {show("delete") && article && (
              <button type="button" disabled={busy} onClick={() => void remove()} className={`${BTN} ml-auto text-red-200`}>
                Delete
              </button>
            )}
          </div>

          {rejecting && (
            <div className="space-y-2 rounded-2xl border border-white/[0.08] p-4">
              <label htmlFor="reject-note" className="block text-xs font-semibold text-white/70">
                What should the author change?
              </label>
              <textarea id="reject-note" rows={3} maxLength={500} value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} className={`${INPUT} py-2`} />
              <button type="button" disabled={busy} onClick={() => void reject()} className={PRIMARY}>
                Send back to author
              </button>
            </div>
          )}
        </form>
      )}

      {tab === "preview" && (
        <article aria-label="Preview of the last saved version" className="space-y-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5">
          {!article ? (
            <p className="text-sm text-white/50">Save the article first to preview it.</p>
          ) : (
            <>
              <p className="text-[11px] uppercase tracking-wide text-amber-200/80">Preview — last saved version{status === "published" ? "" : ", not public"}</p>
              <h2 className="text-2xl font-bold text-white">{article.title}</h2>
              {article.featured_image_url && (
                <div className="relative aspect-[16/9] overflow-hidden rounded-xl bg-white/[0.04]">
                  <Image src={article.featured_image_url} alt={article.featured_image_alt || article.title} fill sizes="640px" className="object-cover" unoptimized />
                </div>
              )}
              {article.excerpt && <p className="font-medium text-white/90">{article.excerpt}</p>}
              <ArticleBody html={article.content} />
              {article.gallery.length > 0 && (
                <ul className="grid grid-cols-3 gap-2">
                  {article.gallery.map((g) => (
                    <li key={g.media_id} className="relative aspect-[4/3] overflow-hidden rounded-lg bg-white/[0.04]">
                      <Image src={g.thumb_url} alt={g.alt} fill sizes="200px" className="object-cover" unoptimized />
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </article>
      )}

      {tab === "history" && article && (
        <RevisionsPanel
          articleId={article.id}
          canWrite={canWrite}
          onRestored={() => {
            setMessage({ kind: "ok", text: "Version restored." })
            setTab("edit")
            void load()
          }}
        />
      )}
    </div>
  )
}

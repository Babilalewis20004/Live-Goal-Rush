import { Image } from "expo-image"
import * as ImagePicker from "expo-image-picker"
import { router, useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native"

import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { ArticleBlocks } from "@/components/news/article-blocks"
import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { STATUS_HELP, availableActions, formatBytes, fromLocalInput, toLocalInput, validateSchedule, validateUpload, type EditorialAction, type StaffRole } from "@/lib/editorial"
import { theme } from "@/theme"
import type { ArticleAdminOut, ArticleStatus, CategoryOut } from "@/types/api"

const STATUS_LABEL: Record<ArticleStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  scheduled: "Scheduled",
  published: "Published",
  archived: "Archived",
}

interface Gallery {
  media_id: number
  caption: string
  thumb_url: string
}

/** Write, upload, preview and move an article through the editorial workflow.
 * The buttons shown come from `availableActions` (mirroring the server's rules for
 * authors / editors / admins); the API enforces them regardless. `id` is a number,
 * or `new` for a fresh draft. */
export default function EditorArticleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { user, loading: authLoading } = useAuth()
  const articleId = id === "new" ? undefined : Number(id)
  const role = user && (user.role === "author" || user.role === "editor" || user.role === "admin") ? (user.role as StaffRole) : null
  const reviewer = role === "editor" || role === "admin"

  const [article, setArticle] = useState<ArticleAdminOut | null>(null)
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [loading, setLoading] = useState(articleId !== undefined)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [title, setTitle] = useState("")
  const [excerpt, setExcerpt] = useState("")
  const [content, setContent] = useState("")
  const [tags, setTags] = useState("")
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [featured, setFeatured] = useState<{ id: number; url: string } | null>(null)
  const [altText, setAltText] = useState("")
  const [gallery, setGallery] = useState<Gallery[]>([])
  const [publishAt, setPublishAt] = useState("")
  const [unpublishAt, setUnpublishAt] = useState("")
  const [rejectNote, setRejectNote] = useState("")
  const [rejecting, setRejecting] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null)

  const adopt = useCallback((a: ArticleAdminOut) => {
    setArticle(a)
    setTitle(a.title)
    setExcerpt(a.excerpt)
    setContent(a.content)
    setTags(a.tags.map((t) => t.name).join(", "))
    setCategoryId(a.category?.id ?? null)
    setFeatured(a.featured_media_id && a.featured_image_url ? { id: a.featured_media_id, url: a.featured_image_url } : null)
    setAltText(a.featured_image_alt ?? "")
    setGallery(a.gallery.map((g) => ({ media_id: g.media_id, caption: g.caption, thumb_url: g.thumb_url })))
    setPublishAt(toLocalInput(a.publish_at))
    setUnpublishAt(toLocalInput(a.unpublish_at))
  }, [])

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const [cats, existing] = await Promise.all([api.getEditorCategories(), articleId !== undefined ? api.getEditorArticle(articleId) : Promise.resolve(null)])
      setCategories(cats)
      if (existing) adopt(existing)
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Couldn't load the article.")
    } finally {
      setLoading(false)
    }
  }, [articleId, adopt])

  useEffect(() => {
    if (authLoading || !role) return
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [authLoading, role, load])

  if (authLoading || (role && loading)) return <View style={styles.screen}><LoadingState label="Loading editor…" /></View>
  if (!role || !user) return <View style={styles.screen}><ErrorState message="You need a writer or editor account to use this." /></View>
  if (loadError) return <View style={styles.screen}><ErrorState message={loadError} onRetry={load} /></View>

  const status: ArticleStatus = article?.status ?? "draft"
  const isOwner = !article || article.author_id === user.id
  const actions = availableActions(role, status, isOwner)
  const canWrite = actions.includes("save")
  const has = (a: EditorialAction) => actions.includes(a)

  const parsedTags = tags.split(",").map((t) => t.trim()).filter(Boolean).slice(0, 10)
  const input = () => ({
    title: title.trim(),
    excerpt: excerpt.trim(),
    content,
    category_id: categoryId,
    tags: parsedTags,
    featured_media_id: featured?.id ?? null,
    featured_image_alt: featured ? altText.trim() || null : null,
    gallery: gallery.map((g) => ({ media_id: g.media_id, caption: g.caption })),
    ...(reviewer ? { publish_at: fromLocalInput(publishAt), unpublish_at: fromLocalInput(unpublishAt) } : {}),
  })

  function problem(forPublish: boolean): string | null {
    if (title.trim().length < 3) return "Give the article a title of at least 3 characters."
    if (forPublish && !content.replace(/<[^>]*>/g, "").trim()) return "Add some content first."
    return null
  }

  async function run(action: () => Promise<ArticleAdminOut>, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      const saved = await action()
      adopt(saved)
      setMessage({ kind: "ok", text: success })
      if (articleId === undefined) router.replace({ pathname: "/editor/[id]", params: { id: String(saved.id) } })
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Something went wrong. Nothing was lost — try again." })
    } finally {
      setBusy(false)
    }
  }

  const ensureSaved = async (): Promise<ArticleAdminOut> => {
    if (!canWrite && article) return article
    return article ? api.updateArticle(article.id, input()) : api.createArticle(input())
  }

  function save() {
    const p = problem(false)
    if (p) return setMessage({ kind: "error", text: p })
    void run(ensureSaved, "Saved.")
  }

  function act(action: EditorialAction) {
    const needsContent = action === "submit" || action === "approve" || action === "publish" || action === "schedule"
    const p = problem(needsContent)
    if (p) return setMessage({ kind: "error", text: p })
    if (action === "schedule") {
      const s = validateSchedule(publishAt, unpublishAt)
      if (s) return setMessage({ kind: "error", text: s })
    }
    const when = fromLocalInput(publishAt)
    const until = fromLocalInput(unpublishAt)
    const flows: Partial<Record<EditorialAction, [() => Promise<ArticleAdminOut>, string]>> = {
      submit: [async () => api.submitArticle((await ensureSaved()).id), "Submitted for review."],
      withdraw: [async () => api.withdrawArticle((await ensureSaved()).id), "Withdrawn. You can edit it again."],
      approve: [async () => api.approveArticle((await ensureSaved()).id, when ? { publish_at: when, unpublish_at: until ?? undefined } : {}), when ? "Approved and scheduled." : "Approved and published."],
      publish: [async () => api.setArticleStatus((await ensureSaved()).id, "publish"), "Published."],
      schedule: [async () => api.scheduleArticle((await ensureSaved()).id, when!, until ?? undefined), "Scheduled."],
      unpublish: [async () => api.setArticleStatus((await ensureSaved()).id, "unpublish"), "Moved back to draft."],
      archive: [async () => api.setArticleStatus((await ensureSaved()).id, "archive"), "Archived."],
    }
    const flow = flows[action]
    if (flow) void run(flow[0], flow[1])
  }

  async function pickImage(target: "featured" | "gallery") {
    setMessage(null)
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync()
    if (!permission.granted) return setMessage({ kind: "error", text: "Allow photo access in Settings to add images." })
    const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1, allowsEditing: false })
    if (picked.canceled || picked.assets.length === 0) return
    const asset = picked.assets[0]
    const file = { uri: asset.uri, name: asset.fileName ?? "photo.jpg", type: asset.mimeType ?? "image/jpeg" }
    const bad = validateUpload({ ...file, size: asset.fileSize ?? 1 })
    if (bad) return setMessage({ kind: "error", text: bad })
    setBusy(true)
    try {
      const media = await api.uploadMedia(file, { altText: target === "featured" ? altText : undefined })
      if (target === "featured") setFeatured({ id: media.id, url: media.url })
      else setGallery((g) => (g.some((x) => x.media_id === media.id) ? g : [...g, { media_id: media.id, caption: "", thumb_url: media.thumb_url }]))
      setMessage({ kind: "ok", text: `Uploaded${asset.fileSize ? ` (${formatBytes(asset.fileSize)})` : ""}. Save to keep it on the article.` })
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Upload failed." })
    } finally {
      setBusy(false)
    }
  }

  async function reject() {
    if (!article) return
    await run(() => api.rejectArticle(article.id, rejectNote.trim()), "Sent back to the author.")
    setRejecting(false)
    setRejectNote("")
  }

  const btn = (label: string, action: EditorialAction, primary = false) =>
    has(action) ? (
      <Pressable key={action} accessibilityRole="button" disabled={busy} onPress={() => act(action)} style={[primary ? styles.primary : styles.secondary, busy && { opacity: 0.5 }]}>
        <Text style={primary ? styles.primaryText : styles.secondaryText}>{label}</Text>
      </Pressable>
    ) : null

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Text style={styles.status} accessibilityLiveRegion="polite">
        Status: <Text style={{ fontWeight: "700", color: theme.text }}>{STATUS_LABEL[status]}</Text> — {STATUS_HELP[status]}
        {status === "scheduled" && article?.publish_at ? ` Goes live ${new Date(article.publish_at).toLocaleString()}.` : ""}
      </Text>
      {article?.review_note && status === "draft" ? (
        <View style={styles.note} accessibilityRole="alert">
          <Text style={styles.noteText}>Changes requested: {article.review_note}</Text>
        </View>
      ) : null}
      {!canWrite && article ? <Text style={styles.status}>You can read this article but not change it in its current state.</Text> : null}

      <View style={styles.tabs} accessibilityRole="tablist">
        {[
          { id: false, label: "Edit" },
          { id: true, label: "Preview" },
        ].map((t) => (
          <Pressable key={t.label} accessibilityRole="tab" accessibilityState={{ selected: previewing === t.id }} onPress={() => setPreviewing(t.id)} style={[styles.tab, previewing === t.id && styles.tabOn]}>
            <Text style={[styles.tabText, previewing === t.id && { color: theme.text }]}>{t.label}</Text>
          </Pressable>
        ))}
      </View>

      {previewing ? (
        <View style={styles.card} accessibilityLabel="Preview of the last saved version">
          {!article ? (
            <Text style={styles.status}>Save the article first to preview it.</Text>
          ) : (
            <>
              <Text style={styles.previewTag}>Preview — last saved version{status === "published" ? "" : ", not public"}</Text>
              <Text accessibilityRole="header" style={styles.previewTitle}>
                {article.title}
              </Text>
              {article.featured_image_url ? <Image source={{ uri: article.featured_image_url }} accessibilityLabel={article.featured_image_alt || article.title} style={styles.previewImage} contentFit="cover" /> : null}
              {article.excerpt ? <Text style={styles.previewExcerpt}>{article.excerpt}</Text> : null}
              <ArticleBlocks blocks={article.content_blocks} fallback={article.content_text} />
            </>
          )}
        </View>
      ) : (
        <View style={{ gap: 14 }}>
          <Field label="Headline">
            <TextInput accessibilityLabel="Headline" editable={canWrite} value={title} onChangeText={setTitle} maxLength={200} style={styles.input} />
          </Field>
          <Field label="Summary">
            <TextInput accessibilityLabel="Summary" editable={canWrite} value={excerpt} onChangeText={setExcerpt} maxLength={500} multiline style={[styles.input, { minHeight: 64 }]} />
          </Field>
          <Field label="Article body (HTML — scripts and styles are removed on save)">
            <TextInput accessibilityLabel="Article body" editable={canWrite} value={content} onChangeText={setContent} multiline autoCapitalize="none" autoCorrect={false} style={[styles.input, { minHeight: 200, fontFamily: "monospace" }]} />
          </Field>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Featured image</Text>
            {featured ? <Image source={{ uri: featured.url }} accessibilityLabel={altText || "Featured image"} style={styles.thumb} contentFit="cover" /> : <Text style={styles.status}>No image chosen.</Text>}
            <TextInput accessibilityLabel="Image description" editable={canWrite} placeholder="Describe the image (read by screen readers)" placeholderTextColor={theme.textFaint} value={altText} onChangeText={setAltText} maxLength={200} style={styles.input} />
            <View style={{ flexDirection: "row", gap: 8 }}>
              {canWrite ? (
                <Pressable accessibilityRole="button" disabled={busy} onPress={() => void pickImage("featured")} style={styles.secondary}>
                  <Text style={styles.secondaryText}>{featured ? "Replace image" : "Upload an image"}</Text>
                </Pressable>
              ) : null}
              {featured && canWrite ? (
                <Pressable accessibilityRole="button" onPress={() => setFeatured(null)} style={styles.secondary}>
                  <Text style={styles.secondaryText}>Remove</Text>
                </Pressable>
              ) : null}
            </View>
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Gallery</Text>
            {gallery.length === 0 ? <Text style={styles.status}>No gallery images.</Text> : null}
            {gallery.map((g, i) => (
              <View key={g.media_id} style={styles.galleryRow}>
                <Image source={{ uri: g.thumb_url }} accessibilityLabel={g.caption || `Gallery image ${i + 1}`} style={styles.galleryThumb} contentFit="cover" />
                <TextInput
                  accessibilityLabel={`Caption for gallery image ${i + 1}`}
                  editable={canWrite}
                  value={g.caption}
                  placeholder="Caption"
                  placeholderTextColor={theme.textFaint}
                  onChangeText={(caption) => setGallery((cur) => cur.map((x) => (x.media_id === g.media_id ? { ...x, caption } : x)))}
                  style={[styles.input, { flex: 1, minHeight: 40 }]}
                />
                {canWrite ? (
                  <Pressable accessibilityRole="button" accessibilityLabel={`Remove gallery image ${i + 1}`} onPress={() => setGallery((cur) => cur.filter((x) => x.media_id !== g.media_id))} style={styles.iconBtn}>
                    <Text style={styles.secondaryText}>×</Text>
                  </Pressable>
                ) : null}
              </View>
            ))}
            {canWrite ? (
              <Pressable accessibilityRole="button" disabled={busy} onPress={() => void pickImage("gallery")} style={styles.secondary}>
                <Text style={styles.secondaryText}>Add gallery image</Text>
              </Pressable>
            ) : null}
          </View>

          <Field label="Category">
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
              {[{ id: null as number | null, name: "None" }, ...categories].map((c) => {
                const selected = categoryId === c.id
                return (
                  <Pressable key={String(c.id)} accessibilityRole="button" accessibilityState={{ selected }} disabled={!canWrite} onPress={() => setCategoryId(c.id)} style={[styles.chip, selected && styles.chipOn]}>
                    <Text style={[styles.chipText, selected && { color: theme.background }]}>{c.name}</Text>
                  </Pressable>
                )
              })}
            </ScrollView>
          </Field>
          <Field label="Tags (comma separated, up to 10)">
            <TextInput accessibilityLabel="Tags" editable={canWrite} value={tags} onChangeText={setTags} autoCapitalize="none" style={styles.input} />
          </Field>

          {reviewer ? (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Scheduling (your local time)</Text>
              <TextInput accessibilityLabel="Publish at" placeholder="Publish at — 2026-10-08 14:30" placeholderTextColor={theme.textFaint} value={publishAt} onChangeText={setPublishAt} autoCapitalize="none" style={styles.input} />
              <TextInput accessibilityLabel="Archive automatically at" placeholder="Archive at (optional) — 2026-10-15 09:00" placeholderTextColor={theme.textFaint} value={unpublishAt} onChangeText={setUnpublishAt} autoCapitalize="none" style={styles.input} />
            </View>
          ) : null}

          {message ? (
            <Text accessibilityRole={message.kind === "error" ? "alert" : undefined} accessibilityLiveRegion="polite" style={message.kind === "error" ? styles.error : styles.success}>
              {message.text}
            </Text>
          ) : null}

          <View style={{ gap: 8 }}>
            {has("save") ? (
              <Pressable accessibilityRole="button" disabled={busy} onPress={save} style={[styles.secondary, busy && { opacity: 0.5 }]}>
                <Text style={styles.secondaryText}>{article ? "Save changes" : "Save draft"}</Text>
              </Pressable>
            ) : null}
            {btn("Submit for review", "submit", !reviewer)}
            {btn(reviewer ? "Back to draft" : "Withdraw from review", "withdraw")}
            {btn(publishAt ? "Approve & schedule" : "Approve & publish", "approve", true)}
            {has("reject") ? (
              <Pressable accessibilityRole="button" accessibilityState={{ expanded: rejecting }} onPress={() => setRejecting((v) => !v)} style={styles.secondary}>
                <Text style={styles.secondaryText}>Request changes</Text>
              </Pressable>
            ) : null}
            {btn("Publish now", "publish", true)}
            {btn("Schedule", "schedule")}
            {btn(status === "scheduled" ? "Cancel schedule" : "Unpublish", "unpublish")}
            {btn("Archive", "archive")}
          </View>

          {rejecting ? (
            <View style={styles.card}>
              <TextInput accessibilityLabel="What should the author change?" placeholder="What should the author change?" placeholderTextColor={theme.textFaint} value={rejectNote} onChangeText={setRejectNote} multiline maxLength={500} style={[styles.input, { minHeight: 72 }]} />
              <Pressable accessibilityRole="button" disabled={busy} onPress={() => void reject()} style={styles.primary}>
                <Text style={styles.primaryText}>Send back to author</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      )}
    </ScrollView>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.label}>{label}</Text>
      {children}
    </View>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, gap: 14, paddingBottom: 64 },
  status: { color: theme.textMuted, fontSize: 12, lineHeight: 17 },
  note: { padding: 12, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: "rgba(251,191,36,0.4)", backgroundColor: "rgba(251,191,36,0.1)" },
  noteText: { color: "#fde68a", fontSize: 13 },
  tabs: { flexDirection: "row", gap: 4, padding: 4, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border },
  tab: { flex: 1, minHeight: 40, alignItems: "center", justifyContent: "center", borderRadius: 8 },
  tabOn: { backgroundColor: "rgba(255,255,255,0.1)" },
  tabText: { color: theme.textMuted, fontWeight: "600", fontSize: 13 },
  label: { color: theme.textMuted, fontSize: 12, fontWeight: "600" },
  input: { minHeight: 44, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card, color: theme.text, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, textAlignVertical: "top" },
  card: { padding: 14, borderRadius: 16, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card, gap: 10 },
  cardTitle: { color: theme.text, fontSize: 14, fontWeight: "700" },
  thumb: { width: "100%", aspectRatio: 16 / 9, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.05)" },
  galleryRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  galleryThumb: { width: 56, height: 42, borderRadius: 6, backgroundColor: "rgba(255,255,255,0.05)" },
  iconBtn: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  chip: { minHeight: 36, paddingHorizontal: 14, justifyContent: "center", borderRadius: 999, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card },
  chipOn: { backgroundColor: theme.emerald, borderColor: theme.emerald },
  chipText: { color: theme.textMuted, fontSize: 13, fontWeight: "600" },
  primary: { minHeight: 48, borderRadius: 12, backgroundColor: theme.emerald, alignItems: "center", justifyContent: "center" },
  primaryText: { color: theme.background, fontWeight: "700", fontSize: 14 },
  secondary: { minHeight: 48, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card, alignItems: "center", justifyContent: "center", paddingHorizontal: 14 },
  secondaryText: { color: theme.text, fontWeight: "600", fontSize: 14 },
  error: { color: "#fca5a5", fontSize: 13 },
  success: { color: theme.emerald, fontSize: 13 },
  previewTag: { color: "#fde68a", fontSize: 11, textTransform: "uppercase" },
  previewTitle: { color: theme.text, fontSize: 22, fontWeight: "700" },
  previewImage: { width: "100%", aspectRatio: 16 / 9, borderRadius: 10 },
  previewExcerpt: { color: theme.text, fontSize: 15, fontWeight: "500" },
})

"use client"

import Image from "next/image"
import { useCallback, useEffect, useId, useRef, useState } from "react"

import { ApiError, api } from "@/lib/api"
import { ACCEPTED_TYPES, formatBytes, validateUpload } from "@/lib/editorial"
import type { FolderOut, MediaOut } from "@/types/api"

const BTN =
  "min-h-9 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-xs text-white/80 hover:bg-white/[0.1] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

/** Upload, browse and (in "manage" mode) edit/delete images. In "pick" mode it is
 * embedded in the article editor and calls `onPick` for the chosen image.
 *
 * Files are checked here for type and size to save a pointless upload, but the
 * server decides on the file's real contents (it decodes and re-encodes every
 * image), so nothing here is relied on for safety. */
export function MediaLibrary({ mode, onPick }: { mode: "manage" | "pick"; onPick?: (media: MediaOut) => void }) {
  const uid = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const [folders, setFolders] = useState<FolderOut[]>([])
  const [folder, setFolder] = useState<number | undefined>(undefined)
  const [items, setItems] = useState<MediaOut[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [altForUpload, setAltForUpload] = useState("")
  const [messages, setMessages] = useState<{ kind: "ok" | "error"; text: string }[]>([])
  const [newFolder, setNewFolder] = useState("")

  const load = useCallback(
    async (pageNo: number, replace: boolean) => {
      try {
        const result = await api.listMedia(folder, pageNo)
        setItems((current) => (replace ? result.items : [...current, ...result.items.filter((m) => !current.some((x) => x.id === m.id))]))
        setTotal(result.total)
        setPage(result.page)
      } catch (e) {
        setMessages([{ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't load the media library." }])
      } finally {
        setLoading(false)
      }
    },
    [folder],
  )

  useEffect(() => {
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      if (cancelled) return
      setLoading(true)
      await load(1, true)
      try {
        const f = await api.listFolders()
        if (!cancelled) setFolders(f)
      } catch {
        // folders are optional
      }
    })()
    return () => {
      cancelled = true
    }
  }, [load])

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return
    setUploading(true)
    const results: { kind: "ok" | "error"; text: string }[] = []
    for (const file of Array.from(files)) {
      const problem = validateUpload(file)
      if (problem) {
        results.push({ kind: "error", text: problem })
        continue
      }
      try {
        const media = await api.uploadMedia(file, { folderId: folder, altText: files.length === 1 ? altForUpload : undefined })
        setItems((current) => [media, ...current])
        setTotal((n) => n + 1)
        results.push({ kind: "ok", text: `Uploaded ${file.name} (${formatBytes(file.size)} → optimised).` })
      } catch (e) {
        results.push({ kind: "error", text: `${file.name}: ${e instanceof ApiError ? e.message : "upload failed."}` })
      }
    }
    setMessages(results)
    setAltForUpload("")
    setUploading(false)
    if (fileInput.current) fileInput.current.value = ""
  }

  async function saveAlt(media: MediaOut, alt: string) {
    if (alt === media.alt_text) return
    try {
      const updated = await api.updateMedia(media.id, { alt_text: alt })
      setItems((current) => current.map((m) => (m.id === media.id ? updated : m)))
    } catch (e) {
      setMessages([{ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't save the description." }])
    }
  }

  async function remove(media: MediaOut) {
    if (!window.confirm(`Delete ${media.filename || "this image"}? This can't be undone.`)) return
    try {
      await api.deleteMedia(media.id)
      setItems((current) => current.filter((m) => m.id !== media.id))
      setTotal((n) => Math.max(0, n - 1))
    } catch (e) {
      setMessages([{ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't delete it." }])
    }
  }

  async function addFolder() {
    const name = newFolder.trim()
    if (!name) return
    try {
      const created = await api.createFolder(name)
      setFolders((current) => [...current, created])
      setNewFolder("")
    } catch (e) {
      setMessages([{ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't create the folder." }])
    }
  }

  return (
    <section aria-label="Media library" className="space-y-4">
      <div className="space-y-2 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <label htmlFor={`${uid}-file`} className="block text-xs font-semibold text-white/70">
              Upload images
            </label>
            <input
              id={`${uid}-file`}
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPTED_TYPES.join(",")}
              disabled={uploading}
              onChange={(e) => void upload(e.target.files)}
              className="mt-1 block w-full text-xs text-white/70 file:mr-3 file:min-h-9 file:rounded-lg file:border-0 file:bg-emerald-400 file:px-4 file:text-xs file:font-semibold file:text-[#070b09]"
            />
          </div>
          <div className="min-w-0 flex-1">
            <label htmlFor={`${uid}-alt`} className="block text-xs font-semibold text-white/70">
              Description (for one image; read by screen readers)
            </label>
            <input
              id={`${uid}-alt`}
              value={altForUpload}
              onChange={(e) => setAltForUpload(e.target.value)}
              maxLength={200}
              className="mt-1 min-h-9 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 text-xs text-white focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
            />
          </div>
        </div>
        <p className="text-[11px] text-white/40">JPEG, PNG, WebP or GIF, up to 5 MB. Images are resized and converted to WebP; metadata such as location is removed.</p>
        <div aria-live="polite" className="space-y-0.5">
          {uploading && <p className="text-xs text-white/60">Uploading…</p>}
          {messages.map((m, i) => (
            <p key={i} role={m.kind === "error" ? "alert" : "status"} className={`text-xs ${m.kind === "error" ? "text-red-300" : "text-emerald-300"}`}>
              {m.text}
            </p>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`${uid}-folder`} className="text-xs text-white/60">
          Folder
        </label>
        <select
          id={`${uid}-folder`}
          value={folder ?? ""}
          onChange={(e) => {
            setLoading(true)
            setFolder(e.target.value ? Number(e.target.value) : undefined)
          }}
          className="min-h-9 rounded-lg border border-white/10 bg-[#0b100d] px-2 text-xs text-white"
        >
          <option value="">All images</option>
          {folders.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name} ({f.media_count})
            </option>
          ))}
        </select>
        <input
          aria-label="New folder name"
          value={newFolder}
          onChange={(e) => setNewFolder(e.target.value)}
          maxLength={80}
          placeholder="New folder"
          className="min-h-9 w-36 rounded-lg border border-white/10 bg-white/[0.03] px-2 text-xs text-white placeholder:text-white/30"
        />
        <button type="button" onClick={() => void addFolder()} className={BTN}>
          Create
        </button>
      </div>

      {loading && <p className="text-sm text-white/40">Loading…</p>}
      {!loading && items.length === 0 && <p className="text-sm text-white/40">No images yet.</p>}

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {items.map((media) => (
          <li key={media.id} className="overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.03]">
            <div className="relative aspect-[4/3] bg-white/[0.04]">
              <Image src={media.thumb_url} alt={media.alt_text || media.filename || "Uploaded image"} fill sizes="200px" className="object-cover" loading="lazy" unoptimized />
            </div>
            <div className="space-y-1.5 p-2">
              <p className="truncate text-[11px] text-white/50" title={media.filename}>
                {media.filename || "image"} · {media.width}×{media.height}
              </p>
              {mode === "manage" ? (
                <>
                  <label className="sr-only" htmlFor={`${uid}-alt-${media.id}`}>
                    Description of {media.filename}
                  </label>
                  <input
                    id={`${uid}-alt-${media.id}`}
                    defaultValue={media.alt_text}
                    maxLength={200}
                    placeholder="Describe the image"
                    onBlur={(e) => void saveAlt(media, e.target.value)}
                    className="min-h-8 w-full rounded-md border border-white/10 bg-white/[0.03] px-2 text-[11px] text-white placeholder:text-white/30"
                  />
                  <button type="button" onClick={() => void remove(media)} className={`${BTN} w-full text-red-200`}>
                    Delete
                  </button>
                </>
              ) : (
                <button type="button" onClick={() => onPick?.(media)} className={`${BTN} w-full`} aria-label={`Use ${media.filename || "this image"}`}>
                  Use this image
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {items.length < total && (
        <button type="button" onClick={() => void load(page + 1, false)} className={`${BTN} w-full`}>
          Load more ({total - items.length})
        </button>
      )}
    </section>
  )
}

import type { ArticleStatus } from "@/types/api"

export type StaffRole = "author" | "editor" | "admin"

export type EditorialAction =
  | "save"
  | "submit"
  | "withdraw"
  | "approve"
  | "reject"
  | "publish"
  | "schedule"
  | "unpublish"
  | "archive"
  | "delete"

/** What the signed-in person may do with an article, for showing the right buttons.
 * This mirrors `ArticleService` on the server and only decides what to *show*: the
 * server enforces the rules, so a stale or tampered UI cannot do more than it may. */
export function availableActions(role: StaffRole, status: ArticleStatus, isOwner: boolean): EditorialAction[] {
  const reviewer = role === "editor" || role === "admin"
  const out: EditorialAction[] = []
  const canWrite = reviewer || (isOwner && status === "draft")
  if (canWrite) out.push("save")
  switch (status) {
    case "draft":
      if (isOwner || reviewer) out.push("submit")
      if (reviewer) out.push("publish", "schedule")
      break
    case "in_review":
      if (isOwner || reviewer) out.push("withdraw")
      if (reviewer) out.push("approve", "reject", "schedule")
      break
    case "scheduled":
      if (reviewer) out.push("publish", "unpublish")
      break
    case "published":
      if (reviewer) out.push("unpublish", "archive")
      break
    case "archived":
      if (reviewer) out.push("publish", "unpublish")
      break
  }
  if (reviewer || (isOwner && status === "draft")) out.push("delete")
  return out
}

export const STATUS_HELP: Record<ArticleStatus, string> = {
  draft: "Only you (and admins) can see this.",
  in_review: "Waiting for an editor to approve it or ask for changes.",
  scheduled: "Will go live automatically at the publish time.",
  published: "Live on the site.",
  archived: "Taken down; not visible to readers.",
}

/** `2026-10-08T14:30` (what <input type="datetime-local"> uses) from an ISO time, in local time. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** The inverse: a local datetime-local value to an unambiguous ISO (UTC) string, or null. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

/** Why a schedule can't be saved yet (null = fine). `now` is injectable for tests. */
export function validateSchedule(publishAt: string, unpublishAt: string, now: Date = new Date()): string | null {
  const start = fromLocalInput(publishAt)
  if (!start) return "Choose when to publish."
  if (new Date(start) <= now) return "The publish time must be in the future."
  const end = fromLocalInput(unpublishAt)
  if (unpublishAt && !end) return "The unpublish time isn't a valid date."
  if (end && new Date(end) <= new Date(start)) return "The unpublish time must be after the publish time."
  return null
}

// -- uploads ------------------------------------------------------------------------------

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
export const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"]

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Quick checks before sending a file. The server decides on the file's actual
 * contents, so this only saves a pointless upload. */
export function validateUpload(file: { type: string; size: number; name: string }): string | null {
  if (file.size === 0) return `${file.name} is empty.`
  if (!ACCEPTED_TYPES.includes(file.type)) return `${file.name}: only JPEG, PNG, WebP and GIF images are accepted.`
  if (file.size > MAX_UPLOAD_BYTES) return `${file.name} is ${formatBytes(file.size)}; the limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`
  return null
}

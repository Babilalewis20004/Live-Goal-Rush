import { describe, expect, it } from "vitest"

import {
  MAX_UPLOAD_BYTES,
  availableActions,
  formatBytes,
  fromLocalInput,
  toLocalInput,
  validateSchedule,
  validateUpload,
} from "@/lib/editorial"

describe("which buttons each role gets", () => {
  it("an author can write and submit their own draft, and nothing that publishes", () => {
    const a = availableActions("author", "draft", true)
    expect(a).toEqual(expect.arrayContaining(["save", "submit", "delete"]))
    for (const forbidden of ["publish", "schedule", "approve", "reject", "unpublish", "archive"] as const) {
      expect(a).not.toContain(forbidden)
    }
  })

  it("an author's article in review is read-only apart from withdrawing it", () => {
    expect(availableActions("author", "in_review", true)).toEqual(["withdraw"])
    expect(availableActions("author", "published", true)).toEqual([])
    expect(availableActions("author", "draft", false)).toEqual([]) // not theirs
  })

  it("an editor reviews: approve, reject, schedule", () => {
    const a = availableActions("editor", "in_review", false)
    expect(a).toEqual(expect.arrayContaining(["save", "approve", "reject", "schedule", "withdraw", "delete"]))
    expect(a).not.toContain("publish") // approving is how an in-review piece goes live
  })

  it("editors and admins can publish, schedule, unpublish and archive", () => {
    expect(availableActions("editor", "draft", true)).toEqual(expect.arrayContaining(["publish", "schedule", "submit"]))
    expect(availableActions("admin", "published", false)).toEqual(expect.arrayContaining(["unpublish", "archive"]))
    expect(availableActions("editor", "scheduled", false)).toEqual(expect.arrayContaining(["publish", "unpublish"]))
    expect(availableActions("editor", "archived", false)).toEqual(expect.arrayContaining(["publish", "unpublish"]))
  })
})

describe("schedule inputs", () => {
  it("round-trips local datetime values through ISO", () => {
    const local = "2026-10-08T14:30"
    const iso = fromLocalInput(local)
    expect(iso).not.toBeNull()
    expect(toLocalInput(iso)).toBe(local)
    expect(fromLocalInput("")).toBeNull()
    expect(fromLocalInput("not a date")).toBeNull()
    expect(toLocalInput(null)).toBe("")
    expect(toLocalInput("garbage")).toBe("")
  })

  it("validates the publish and unpublish times", () => {
    const now = new Date("2026-10-08T12:00:00")
    expect(validateSchedule("", "", now)).toMatch(/Choose when/)
    expect(validateSchedule("2026-10-08T11:00", "", now)).toMatch(/future/)
    expect(validateSchedule("2026-10-09T10:00", "", now)).toBeNull()
    expect(validateSchedule("2026-10-09T10:00", "2026-10-09T09:00", now)).toMatch(/after the publish time/)
    expect(validateSchedule("2026-10-09T10:00", "2026-10-10T09:00", now)).toBeNull()
    expect(validateSchedule("2026-10-09T10:00", "nonsense", now)).toMatch(/valid date/)
  })
})

describe("upload pre-checks", () => {
  it("accepts supported images within the size limit", () => {
    expect(validateUpload({ name: "a.png", type: "image/png", size: 1000 })).toBeNull()
    expect(validateUpload({ name: "a.webp", type: "image/webp", size: MAX_UPLOAD_BYTES })).toBeNull()
  })

  it("refuses empty, unsupported and oversized files with a reason", () => {
    expect(validateUpload({ name: "a.png", type: "image/png", size: 0 })).toMatch(/empty/)
    expect(validateUpload({ name: "a.svg", type: "image/svg+xml", size: 100 })).toMatch(/only JPEG, PNG, WebP and GIF/)
    expect(validateUpload({ name: "a.pdf", type: "application/pdf", size: 100 })).toMatch(/only JPEG/)
    expect(validateUpload({ name: "big.jpg", type: "image/jpeg", size: MAX_UPLOAD_BYTES + 1 })).toMatch(/limit is 5\.0 MB/)
  })

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B")
    expect(formatBytes(2048)).toBe("2 KB")
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB")
  })
})

import { availableActions, formatBytes, fromLocalInput, toLocalInput, validateSchedule, validateUpload, MAX_UPLOAD_BYTES } from "@/lib/editorial"

describe("which buttons each role gets (mirrors the server)", () => {
  it("an author writes and submits but never publishes", () => {
    const a = availableActions("author", "draft", true)
    expect(a).toEqual(expect.arrayContaining(["save", "submit", "delete"]))
    for (const forbidden of ["publish", "schedule", "approve", "reject", "unpublish", "archive"] as const) expect(a).not.toContain(forbidden)
    expect(availableActions("author", "in_review", true)).toEqual(["withdraw"])
    expect(availableActions("author", "published", true)).toEqual([])
    expect(availableActions("author", "draft", false)).toEqual([])
  })

  it("an editor reviews and publishes", () => {
    expect(availableActions("editor", "in_review", false)).toEqual(expect.arrayContaining(["approve", "reject", "schedule", "save"]))
    expect(availableActions("admin", "published", false)).toEqual(expect.arrayContaining(["unpublish", "archive"]))
  })
})

describe("typed date-times", () => {
  it("round-trip through ISO and reject anything else", () => {
    const iso = fromLocalInput("2026-10-08 14:30")
    expect(iso).not.toBeNull()
    expect(toLocalInput(iso)).toBe("2026-10-08 14:30")
    expect(fromLocalInput("2026-10-08T14:30")).not.toBeNull()
    for (const bad of ["", "tomorrow", "2026-13-45 99:99", "08/10/2026 14:30"]) expect(fromLocalInput(bad)).toBeNull()
    expect(toLocalInput(null)).toBe("")
  })

  it("validates a schedule", () => {
    const now = new Date("2026-10-08T12:00:00")
    expect(validateSchedule("", "", now)).toMatch(/Choose when/)
    expect(validateSchedule("2026-10-08 11:00", "", now)).toMatch(/future/)
    expect(validateSchedule("2026-10-09 10:00", "", now)).toBeNull()
    expect(validateSchedule("2026-10-09 10:00", "2026-10-09 09:00", now)).toMatch(/after the publish time/)
  })
})

describe("upload pre-checks", () => {
  it("accepts supported images and explains refusals", () => {
    expect(validateUpload({ name: "a.jpg", type: "image/jpeg", size: 1000 })).toBeNull()
    expect(validateUpload({ name: "a.svg", type: "image/svg+xml", size: 10 })).toMatch(/only JPEG/)
    expect(validateUpload({ name: "big.png", type: "image/png", size: MAX_UPLOAD_BYTES + 1 })).toMatch(/limit/)
    expect(validateUpload({ name: "e.png", type: "image/png", size: 0 })).toMatch(/empty/)
    expect(formatBytes(2048)).toBe("2 KB")
  })
})

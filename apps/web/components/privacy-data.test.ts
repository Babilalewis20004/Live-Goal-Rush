import { describe, expect, it, vi } from "vitest"

import { downloadJson, exportFilename } from "./privacy-data"

describe("privacy export helpers", () => {
  it("names the file by date and never by identity", () => {
    expect(exportFilename(new Date("2026-10-08T12:34:56Z"))).toBe("livepitch-my-data-2026-10-08.json")
  })

  it("hands the browser a JSON blob to save and releases it afterwards", () => {
    const created: Blob[] = []
    const createObjectURL = vi.fn((blob: Blob) => {
      created.push(blob)
      return "blob:fake"
    })
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)

    downloadJson("data.json", { account: { id: 1 } })

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(created[0].type).toBe("application/json")
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake")
    expect(document.querySelector("a[download]")).toBeNull() // the temporary link is removed
  })
})

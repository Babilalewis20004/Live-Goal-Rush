import { beforeEach, describe, expect, it } from "vitest"

import {
  MAX_RECENT,
  RECENT_KEY,
  addRecent,
  clearRecent,
  normalizeSearch,
  readRecent,
  removeRecent,
} from "@/lib/search-history"

function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, String(v)),
  }
}

describe("anonymous recent searches", () => {
  let storage: Storage
  beforeEach(() => {
    storage = memoryStorage()
  })

  it("normalises whitespace and length", () => {
    expect(normalizeSearch("  man   utd \n")).toBe("man utd")
    expect(normalizeSearch("x".repeat(300))).toHaveLength(100)
  })

  it("keeps the newest first and unique ignoring case", () => {
    addRecent("arsenal", storage)
    addRecent("chelsea", storage)
    addRecent("ARSENAL", storage)
    expect(readRecent(storage)).toEqual(["ARSENAL", "chelsea"])
  })

  it("caps the list and ignores one-character queries", () => {
    for (let i = 0; i < MAX_RECENT + 5; i++) addRecent(`query ${i}`, storage)
    addRecent("a", storage)
    const recent = readRecent(storage)
    expect(recent).toHaveLength(MAX_RECENT)
    expect(recent[0]).toBe(`query ${MAX_RECENT + 4}`)
  })

  it("removes one entry or clears everything", () => {
    addRecent("one", storage)
    addRecent("two", storage)
    expect(removeRecent("ONE", storage)).toEqual(["two"])
    expect(clearRecent(storage)).toEqual([])
    expect(readRecent(storage)).toEqual([])
  })

  it("survives corrupted or hostile storage contents", () => {
    storage.setItem(RECENT_KEY, "{not json")
    expect(readRecent(storage)).toEqual([])
    storage.setItem(RECENT_KEY, JSON.stringify([1, { a: 1 }, "ok", null]))
    expect(readRecent(storage)).toEqual(["ok"])
    storage.setItem(RECENT_KEY, JSON.stringify({ not: "an array" }))
    expect(readRecent(storage)).toEqual([])
  })

  it("works without any storage (private mode, SSR)", () => {
    expect(readRecent(null)).toEqual([])
    expect(addRecent("arsenal", null)).toEqual(["arsenal"])
    expect(clearRecent(null)).toEqual([])
  })
})

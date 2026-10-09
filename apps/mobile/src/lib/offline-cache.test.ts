import AsyncStorage from "@react-native-async-storage/async-storage"

import { MAX_AGE_MS, clearCopies, loadCopy, saveCopy } from "./offline-cache"

beforeEach(async () => {
  await AsyncStorage.clear()
})

describe("offline cache", () => {
  it("round-trips a saved copy with the time it was saved", async () => {
    await saveCopy("board", { live: [1, 2] }, 1_000)
    expect(await loadCopy("board", 2_000)).toEqual({ data: { live: [1, 2] }, savedAt: 1_000 })
  })

  it("returns nothing for a key that was never saved", async () => {
    expect(await loadCopy("nope")).toBeNull()
  })

  it("will not offer a copy older than a day", async () => {
    await saveCopy("board", { live: [] }, 0)
    expect(await loadCopy("board", MAX_AGE_MS + 1)).toBeNull()
    expect(await loadCopy("board", MAX_AGE_MS - 1)).not.toBeNull()
  })

  it("ignores a corrupted entry instead of crashing the screen", async () => {
    await AsyncStorage.setItem("livepitch:cache:v1:board", "{not json")
    expect(await loadCopy("board")).toBeNull()
  })

  it("never throws when storage fails", async () => {
    // Once: restoring a spy on the library's own jest.fn would leave setItem as a no-op for the tests after this one.
    jest.spyOn(AsyncStorage, "setItem").mockRejectedValueOnce(new Error("disk full"))
    await expect(saveCopy("board", {})).resolves.toBeUndefined()
  })

  it("clears only its own entries", async () => {
    await AsyncStorage.setItem("something-else", "keep")
    await saveCopy("board", {})
    await clearCopies()
    expect(await loadCopy("board")).toBeNull()
    expect(await AsyncStorage.getItem("something-else")).toBe("keep")
  })
})

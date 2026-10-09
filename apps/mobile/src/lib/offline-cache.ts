/**
 * A tiny on-device copy of the last good response (Phase 7 degraded mode), so a cold start with no network can
 * still show something -- clearly marked as old -- instead of an error screen.
 *
 * Only public, non-personal data belongs here (match lists). Everything is best-effort: a storage failure must
 * never break the screen, so every call swallows its errors.
 */
import AsyncStorage from "@react-native-async-storage/async-storage"

const PREFIX = "livepitch:cache:v1:"
/** Older than this is not worth showing, even marked as old. */
export const MAX_AGE_MS = 24 * 60 * 60 * 1000

export interface Saved<T> {
  data: T
  savedAt: number
}

export async function saveCopy<T>(key: string, data: T, now: number = Date.now()): Promise<void> {
  try {
    await AsyncStorage.setItem(PREFIX + key, JSON.stringify({ data, savedAt: now } satisfies Saved<T>))
  } catch {
    // out of space / storage unavailable: carry on without a saved copy
  }
}

export async function loadCopy<T>(key: string, now: number = Date.now()): Promise<Saved<T> | null> {
  try {
    const raw = await AsyncStorage.getItem(PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Saved<T>
    if (typeof parsed?.savedAt !== "number" || now - parsed.savedAt > MAX_AGE_MS) return null
    return parsed
  } catch {
    return null
  }
}

export async function clearCopies(): Promise<void> {
  try {
    const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith(PREFIX))
    await AsyncStorage.multiRemove(keys)
  } catch {
    // nothing to do
  }
}

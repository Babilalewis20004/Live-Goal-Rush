import { api } from "@/lib/api"

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/")
  const rawData = atob(base64)
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)))
}

export function isPushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window
}

/** Full round trip (Phase 3 §18): browser permission prompt, VAPID-keyed
 * `PushSubscription`, then registers it with the backend as a `Device`.
 * Returns `false` (never throws) on any step that isn't available or is
 * declined -- the app must keep working with push simply off. */
export async function subscribeToPush(): Promise<boolean> {
  if (!isPushSupported()) return false

  const permission = await Notification.requestPermission()
  if (permission !== "granted") return false

  const { public_key: vapidPublicKey } = await api.getVapidPublicKey()
  if (!vapidPublicKey) return false

  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
  })

  const json = subscription.toJSON()
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return false

  await api.subscribeWebPush(json.endpoint, json.keys.p256dh, json.keys.auth)
  return true
}

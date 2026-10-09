// Hand-rolled (no next-pwa) -- consistent with this repo's existing
// hand-rolled resilient-client style (see lib/realtime.ts). Two jobs:
// show an incoming Web Push message, and route a tap to the right page
// using the same {type, id} payload contract the Expo app's tap handler
// reads (Phase 3 §18).

self.addEventListener("push", (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { title: "LivePitch", body: event.data ? event.data.text() : "" }
  }

  const title = payload.title || "LivePitch"
  const options = {
    body: payload.body || "",
    icon: "/icon-light-32x32.png",
    badge: "/icon-light-32x32.png",
    data: payload.data || {},
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener("notificationclick", (event) => {
  event.notification.close()
  const data = event.notification.data || {}
  // Same contract as the mobile app: only these pages, and the id (for an
  // article, its slug) must look like an id -- a malformed payload opens "/".
  const TYPES = ["match", "team", "competition", "player", "article", "poll", "editor"]
  const id = data.id != null ? String(data.id) : ""
  const path =
    data.type === "premium"
      ? "/premium" // subscription notices: one page, no id
      : TYPES.includes(data.type) && /^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$/.test(id)
        ? `/${data.type}/${id}`
        : "/"

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      const existing = clientList.find((client) => client.url.includes(path))
      if (existing) return existing.focus()
      return self.clients.openWindow(path)
    }),
  )
})

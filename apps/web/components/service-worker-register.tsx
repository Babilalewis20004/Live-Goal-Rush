"use client"

import { useEffect } from "react"

/** Registers the service worker that Web Push (Phase 3 §18) needs to
 * receive `push`/`notificationclick` events -- harmless no-op in browsers
 * without support, and failure here never blocks anything else the app
 * does (push is additive, never required). */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Not fatal -- push notifications simply won't be available.
    })
  }, [])

  return null
}

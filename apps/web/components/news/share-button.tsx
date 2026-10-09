"use client"

import { Check, Share2 } from "lucide-react"
import { useState } from "react"

/** Share a public page. `url` is always the canonical absolute URL built on
 * the server from a path -- never `window.location`, which could carry query
 * strings -- so nothing about the visitor (session, filters) is ever shared.
 * Uses the native share sheet where the browser has one, otherwise copies. */
export function ShareButton({ url, title, label = "Share" }: { url: string; title: string; label?: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle")

  async function share() {
    try {
      if (typeof navigator.share === "function") {
        await navigator.share({ title, url })
        return
      }
      await navigator.clipboard.writeText(url)
      setStatus("copied")
    } catch (error) {
      if ((error as { name?: string })?.name === "AbortError") return // user closed the share sheet
      setStatus("failed")
    }
    setTimeout(() => setStatus("idle"), 2500)
  }

  return (
    <div className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={share}
        className="inline-flex min-h-10 items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-xs font-medium text-white/80 transition-colors hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
      >
        {status === "copied" ? <Check className="h-4 w-4 text-emerald-300" aria-hidden /> : <Share2 className="h-4 w-4" aria-hidden />}
        {label}
      </button>
      <span role="status" aria-live="polite" className="text-[11px] text-white/50">
        {status === "copied" ? "Link copied" : status === "failed" ? "Couldn't share — copy the address bar instead" : ""}
      </span>
    </div>
  )
}

"use client"

import { useRouter } from "next/navigation"
import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth-context"
import { ApiError, api } from "@/lib/api"

export function exportFilename(now: Date = new Date()): string {
  return `livepitch-my-data-${now.toISOString().slice(0, 10)}.json`
}

/** Hands the browser a JSON file to save. Nothing is stored or uploaded. */
export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/** Download-my-data and delete-my-account (Phase 7 privacy). Both are server-enforced: the password is checked
 * by the API, and the export only ever contains the signed-in person's own data. */
export function PrivacyData() {
  const router = useRouter()
  const { logout } = useAuth()
  const [exporting, setExporting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleExport() {
    setError(null)
    setMessage(null)
    setExporting(true)
    try {
      downloadJson(exportFilename(), await api.exportMyData())
      setMessage("Your data has been downloaded.")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not export your data. Please try again.")
    } finally {
      setExporting(false)
    }
  }

  async function handleDelete(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setDeleting(true)
    try {
      await api.deleteAccount(password)
      await logout().catch(() => undefined) // the session is already gone server-side; this clears local state
      router.replace("/")
      router.refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete your account. Please try again.")
      setDeleting(false)
    }
  }

  return (
    <section className="mb-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-sm font-semibold text-white">Your data</h2>
      <p className="mb-3 text-xs text-white/50">
        Download a copy of what you have given us, or erase your account. Erasing removes your favourites, devices,
        reactions, votes and notification history, and anonymises your comments. Billing records are kept as the law
        requires.
      </p>
      <Button type="button" onClick={handleExport} disabled={exporting} className="mb-3 w-full justify-center">
        {exporting ? "Preparing…" : "Download my data"}
      </Button>

      {!confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="w-full rounded-xl border border-red-400/30 px-3 py-2.5 text-sm font-medium text-red-300 hover:bg-red-400/10"
        >
          Delete my account…
        </button>
      ) : (
        <form onSubmit={handleDelete} className="flex flex-col gap-3 rounded-xl border border-red-400/30 p-3">
          <p className="text-xs text-red-200">
            This cannot be undone. Any subscription is cancelled. Enter your password to confirm.
          </p>
          <input
            type="password"
            required
            autoComplete="current-password"
            aria-label="Password to confirm account deletion"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-white focus:outline-none focus:border-white/30"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                setConfirming(false)
                setPassword("")
                setError(null)
              }}
              className="flex-1 rounded-xl border border-white/10 px-3 py-2.5 text-sm text-white/70 hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={deleting || !password}
              className="flex-1 rounded-xl bg-red-500/90 px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              {deleting ? "Deleting…" : "Delete forever"}
            </button>
          </div>
        </form>
      )}
      {error && <p className="mt-3 text-xs text-red-400">{error}</p>}
      {message && <p className="mt-3 text-xs text-emerald-400">{message}</p>}
    </section>
  )
}

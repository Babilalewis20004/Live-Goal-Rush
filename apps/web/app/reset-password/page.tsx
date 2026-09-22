"use client"

import { useRouter, useSearchParams } from "next/navigation"
import { useState, type FormEvent } from "react"

import { AnimatedBackground } from "@/components/animated-background"
import { Button } from "@/components/ui/button"
import { ApiError, api } from "@/lib/api"

export default function ResetPasswordPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get("token") ?? ""
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.confirmPasswordReset(token, password)
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-sm px-4 pb-16 pt-16">
        <h1 className="mb-6 text-lg font-bold text-white">Choose a new password</h1>
        <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
          {!token ? (
            <p className="text-sm text-red-400">Missing or invalid reset link.</p>
          ) : done ? (
            <div className="flex flex-col gap-3 text-sm text-white/70">
              <p>Your password has been reset.</p>
              <Button onClick={() => router.push("/login")} className="w-full justify-center">
                Log in
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="password" className="text-xs font-medium text-white/60">
                  New password
                </label>
                <input
                  id="password"
                  type="password"
                  required
                  minLength={8}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/30"
                />
              </div>
              {error && <p className="text-xs text-red-400">{error}</p>}
              <Button type="submit" disabled={submitting} className="w-full justify-center">
                {submitting ? "Saving…" : "Save new password"}
              </Button>
            </form>
          )}
        </div>
      </div>
    </main>
  )
}

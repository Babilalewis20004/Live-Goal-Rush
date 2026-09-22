"use client"

import { useState, type FormEvent } from "react"

import { AnimatedBackground } from "@/components/animated-background"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [devResetUrl, setDevResetUrl] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    try {
      // Always succeeds the same way whether or not the email exists
      // (Phase 3 §5) -- no enumeration signal to react to here.
      const result = await api.requestPasswordReset(email)
      setDevResetUrl(result.dev_reset_url)
      setSubmitted(true)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-sm px-4 pb-16 pt-16">
        <h1 className="mb-6 text-lg font-bold text-white">Reset your password</h1>
        <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
          {submitted ? (
            <div className="flex flex-col gap-3 text-sm text-white/70">
              <p>If an account with that email exists, a reset link has been sent.</p>
              {devResetUrl && (
                <p className="text-xs text-white/40">
                  Dev environment only:{" "}
                  <a href={devResetUrl} className="text-white/70 underline">
                    open reset link
                  </a>
                </p>
              )}
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="email" className="text-xs font-medium text-white/60">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/30"
                />
              </div>
              <Button type="submit" disabled={submitting} className="w-full justify-center">
                {submitting ? "Sending…" : "Send reset link"}
              </Button>
            </form>
          )}
        </div>
      </div>
    </main>
  )
}

"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"

import { useAsync } from "@/hooks/use-async"
import { api, ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { formatPrice, subscriptionStatusText } from "@/lib/analytics"
import type { PlanOut, SubscriptionOut } from "@/types/api"

const CARD = "rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md"

const FREE = [
  "Livescores and real-time match updates",
  "The full match centre: events, lineups, statistics, table",
  "Teams, players, competitions, standings",
  "News, search, favourites and notifications",
  "Comments, reactions and polls",
  "Last-5 form, head-to-head and basic team analytics",
  "The headline match estimate",
]
const PREMIUM = [
  "Advanced team analytics: shots, possession, passing, defence, discipline, xG where supplied",
  "Last 10 / 20 / 38 match windows and full head-to-head history",
  "Full team-vs-team match comparison",
  "Detailed estimate breakdown: expected goals per side and the model inputs",
  "Advanced player analytics: per-90 numbers and match-by-match history",
  "An ad-free experience",
]

export function PremiumPage({ checkout }: { checkout?: string }) {
  const { user } = useAuth()
  const plans = useAsync(() => api.getPlans(), "plans")
  const sub = useAsync(() => api.getSubscription(), `subscription:${user?.id ?? "anon"}`, 0, !!user)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const reload = sub.reload
  const status = sub.data?.status

  // Coming back from checkout: the webhook (not this redirect) activates the plan, so wait for it briefly.
  const polls = useRef(0)
  useEffect(() => {
    if (checkout !== "success" || !user || status === "active") return
    const timer = setInterval(() => {
      polls.current += 1
      if (polls.current > 10) clearInterval(timer)
      else reload()
    }, 3000)
    return () => clearInterval(timer)
  }, [checkout, user, status, reload])

  async function subscribe(plan: PlanOut) {
    setBusy(plan.code)
    setError(null)
    try {
      const session = await api.startCheckout(plan.code)
      window.location.assign(session.url)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start checkout.")
      setBusy(null)
    }
  }

  async function cancel() {
    setBusy("cancel")
    setError(null)
    try {
      await api.cancelSubscription()
      setConfirmCancel(false)
      reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't cancel.")
    } finally {
      setBusy(null)
    }
  }

  const current: SubscriptionOut | null = sub.data
  const hasPlan = current && (current.status === "active" || current.status === "past_due" || current.status === "cancelled") && current.entitlements.length > 0

  return (
    <div className="mx-auto max-w-3xl px-4 pb-16 pt-8">
      <h1 className="text-xl font-bold text-white">LivePitch Premium</h1>
      <p className="mt-1 text-sm text-white/60">Deeper analysis for people who like the numbers. The core football experience stays free.</p>

      {checkout === "success" && (
        <p role="status" className="mt-4 rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
          {status === "active" ? "Thanks — Premium is active." : "Thanks! We're confirming your payment; this usually takes a few seconds."}
        </p>
      )}
      {checkout === "cancelled" && (
        <p role="status" className="mt-4 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-white/70">
          Checkout was cancelled. You haven&apos;t been charged.
        </p>
      )}

      {user && current && (
        <section className={`${CARD} mt-4`} aria-labelledby="your-plan">
          <h2 id="your-plan" className="text-sm font-semibold text-white">Your plan</h2>
          <p className="mt-1 text-sm text-white/70">{subscriptionStatusText(current.status, current.cancel_at_period_end, current.current_period_end)}</p>
          {hasPlan && current.status !== "cancelled" && (
            <div className="mt-3">
              {confirmCancel ? (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-white/70">Cancel at the end of the period you&apos;ve paid for?</span>
                  <button type="button" onClick={cancel} disabled={busy === "cancel"} className="rounded-lg bg-red-500/80 px-3 py-1.5 text-white disabled:opacity-50">
                    {busy === "cancel" ? "Cancelling…" : "Yes, cancel"}
                  </button>
                  <button type="button" onClick={() => setConfirmCancel(false)} className="rounded-lg border border-white/15 px-3 py-1.5 text-white/70">Keep Premium</button>
                </div>
              ) : (
                <button type="button" onClick={() => setConfirmCancel(true)} className="text-sm text-white/60 underline-offset-2 hover:text-white hover:underline">Cancel subscription</button>
              )}
            </div>
          )}
        </section>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <section className={CARD} aria-labelledby="free-heading">
          <h2 id="free-heading" className="text-sm font-semibold text-white">Free</h2>
          <ul className="mt-3 space-y-1.5 text-sm text-white/70">
            {FREE.map((f) => (
              <li key={f} className="flex gap-2"><span aria-hidden className="text-emerald-300">✓</span><span>{f}</span></li>
            ))}
          </ul>
        </section>
        <section className={`${CARD} border-emerald-400/25`} aria-labelledby="premium-heading">
          <h2 id="premium-heading" className="text-sm font-semibold text-white">Premium</h2>
          <ul className="mt-3 space-y-1.5 text-sm text-white/80">
            {PREMIUM.map((f) => (
              <li key={f} className="flex gap-2"><span aria-hidden className="text-emerald-300">★</span><span>{f}</span></li>
            ))}
          </ul>
          <div className="mt-4 space-y-2">
            {plans.data?.map((p) => (
              <div key={p.code} className="flex items-center justify-between gap-3 rounded-xl border border-white/10 px-3 py-2">
                <div>
                  <p className="text-sm font-medium text-white">{p.name}</p>
                  <p className="text-xs text-white/60">{formatPrice(p)}</p>
                </div>
                {user ? (
                  <button type="button" onClick={() => subscribe(p)} disabled={!!busy || !!hasPlan}
                    className="rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-black hover:bg-emerald-400 disabled:opacity-40">
                    {busy === p.code ? "Opening…" : hasPlan ? "Subscribed" : "Subscribe"}
                  </button>
                ) : (
                  <Link href="/login?next=/premium" className="rounded-lg border border-white/15 px-3 py-1.5 text-sm text-white/80 hover:text-white">Sign in</Link>
                )}
              </div>
            ))}
            {plans.loading && !plans.data && <p className="text-xs text-white/60">Loading plans…</p>}
            {plans.error && !plans.data && <p className="text-xs text-white/60">Plans can&apos;t be shown right now.</p>}
          </div>
          {error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}
        </section>
      </div>

      <p className="mt-6 text-xs text-white/60">
        Payments are handled by our payment provider on its own page; we never see or store your card details. You can cancel any time and keep Premium until the end of the period you paid for.
        Match estimates are statistical and not betting advice.
      </p>
    </div>
  )
}

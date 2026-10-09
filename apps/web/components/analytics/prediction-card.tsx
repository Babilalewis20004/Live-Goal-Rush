"use client"

import { useAsync } from "@/hooks/use-async"
import { LockedNote } from "@/components/analytics/premium-gate"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { confidenceText, formatNumber, outcomePercentages, timeAgo } from "@/lib/analytics"
import type { PredictionOut } from "@/types/api"

const CARD = "rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-md"

/** The model's estimate for an upcoming match. Always labelled as an estimate, always with the
 * reasons and the caveat; probabilities are shown as numbers (the bar is decoration). */
export function PredictionView({ prediction, homeName, awayName, signedIn }: { prediction: PredictionOut; homeName: string; awayName: string; signedIn: boolean }) {
  if (prediction.status !== "available") {
    return (
      <section className={CARD} aria-label="Model estimate">
        <h2 className="text-sm font-semibold text-white">Model estimate</h2>
        <p className="mt-2 text-xs text-white/60">{prediction.reason ?? "No estimate is available for this match."}</p>
      </section>
    )
  }
  const outcomes = outcomePercentages(prediction, { home: homeName, away: awayName })
  const generated = timeAgo(prediction.generated_at)
  return (
    <section className={CARD} aria-labelledby="prediction-heading">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="prediction-heading" className="text-sm font-semibold text-white">
          Model estimate
        </h2>
        <span className="text-[11px] uppercase tracking-wide text-white/60">Statistical prediction</span>
      </div>

      {outcomes && (
        <>
          <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-white/10" role="img" aria-label={outcomes.map((o) => `${o.label} ${o.percent}%`).join(", ")}>
            <div className="bg-emerald-400" style={{ width: `${outcomes[0].percent}%` }} />
            <div className="bg-white/40" style={{ width: `${outcomes[1].percent}%` }} />
            <div className="bg-sky-400" style={{ width: `${outcomes[2].percent}%` }} />
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
            {outcomes.map((o) => (
              <div key={o.key}>
                <dt className="truncate text-[11px] text-white/60">{o.label}</dt>
                <dd className="text-lg font-semibold text-white">{o.percent}%</dd>
              </div>
            ))}
          </dl>
        </>
      )}

      <p className="mt-3 text-xs text-white/60">
        Expected total goals: <strong className="text-white/80">{formatNumber(prediction.expected_total_goals)}</strong>
        {prediction.expected_home_goals !== null && prediction.expected_away_goals !== null && (
          <>
            {" "}
            ({homeName} {formatNumber(prediction.expected_home_goals)}, {awayName} {formatNumber(prediction.expected_away_goals)})
          </>
        )}
      </p>
      {confidenceText(prediction.confidence) && <p className="mt-1 text-xs text-white/60">{confidenceText(prediction.confidence)}.</p>}

      {prediction.influences.length > 0 && (
        <div className="mt-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-white/60">Prediction influenced by</h3>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-white/60">
            {prediction.influences.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ul>
        </div>
      )}

      <LockedNote locked={prediction.locked} signedIn={signedIn} />
      <p className="mt-3 text-[11px] leading-relaxed text-white/60">
        {prediction.disclaimer} Based on available historical data
        {prediction.model_version ? ` · model ${prediction.model_version}` : ""}
        {generated ? ` · generated ${generated}` : ""}.
      </p>
    </section>
  )
}

export function PredictionCard({ matchId, homeName, awayName, nudge = 0 }: { matchId: number; homeName: string; awayName: string; nudge?: number }) {
  const { user } = useAuth()
  const { data, error, loading } = useAsync(() => api.getMatchPrediction(matchId), `prediction:${matchId}:${user?.id ?? "anon"}`, nudge)
  if (loading && !data) return <section className={CARD} aria-busy="true"><p className="text-xs text-white/60">Loading estimate…</p></section>
  if (error || !data) {
    return (
      <section className={CARD}>
        <h2 className="text-sm font-semibold text-white">Model estimate</h2>
        <p className="mt-2 text-xs text-white/60">The estimate isn&apos;t available right now.</p>
      </section>
    )
  }
  return <PredictionView prediction={data} homeName={homeName} awayName={awayName} signedIn={!!user} />
}

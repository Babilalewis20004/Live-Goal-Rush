"use client"

import { AnimatedBackground } from "@/components/animated-background"
import { ErrorState } from "@/components/ui/error-state"

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pt-24">
        <ErrorState message="Unable to load matches. The football data service may be unavailable." onRetry={reset} />
      </div>
    </main>
  )
}

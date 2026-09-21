import { AnimatedBackground } from "@/components/animated-background"
import { LoadingState } from "@/components/ui/loading-state"

export default function Loading() {
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pt-24">
        <LoadingState label="Loading matches…" />
      </div>
    </main>
  )
}

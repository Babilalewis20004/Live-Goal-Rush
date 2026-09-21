import Link from "next/link"
import { AnimatedBackground } from "@/components/animated-background"
import { EmptyState } from "@/components/ui/empty-state"

export default function NotFound() {
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pt-24">
        <EmptyState message="We couldn't find what you were looking for." />
        <p className="mt-4 text-center text-sm">
          <Link href="/" className="text-emerald-400 hover:underline">
            Back to livescores
          </Link>
        </p>
      </div>
    </main>
  )
}

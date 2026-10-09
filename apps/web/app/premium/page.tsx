import type { Metadata } from "next"

import { AnimatedBackground } from "@/components/animated-background"
import { PremiumPage } from "@/components/premium/premium-page"

export const metadata: Metadata = {
  title: "Premium",
  description: "Advanced analytics, full comparisons and detailed match estimates. Livescores and news stay free.",
}

export default async function Page({ searchParams }: { searchParams: Promise<{ checkout?: string }> }) {
  const { checkout } = await searchParams
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <PremiumPage checkout={checkout} />
    </main>
  )
}

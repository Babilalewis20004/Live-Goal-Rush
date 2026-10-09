import type { Metadata } from "next"

import { AnimatedBackground } from "@/components/animated-background"

// Tooling, not content: never indexed. Access is enforced by the API (role
// checks on every /editor/articles call); the proxy only avoids a flash of
// the page for signed-out visitors.
export const metadata: Metadata = {
  title: "Editor",
  robots: { index: false, follow: false },
}

export default function EditorLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-3xl px-4 pb-16 pt-6">{children}</div>
    </main>
  )
}

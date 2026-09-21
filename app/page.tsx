import { AnimatedBackground } from "@/components/animated-background"
import { LivescoreBoard } from "@/components/livescore-board"

export default function Page() {
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <LivescoreBoard />
    </main>
  )
}

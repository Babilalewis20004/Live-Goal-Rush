import { AnimatedBackground } from "@/components/animated-background"
import { RegisterForm } from "@/components/auth/register-form"

export const dynamic = "force-dynamic"

export default function RegisterPage() {
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-sm px-4 pb-16 pt-16">
        <h1 className="mb-6 text-lg font-bold text-white">Create your account</h1>
        <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
          <RegisterForm />
        </div>
      </div>
    </main>
  )
}

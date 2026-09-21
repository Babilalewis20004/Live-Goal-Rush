export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-12 text-center text-sm text-white/40">
      {message}
    </div>
  )
}

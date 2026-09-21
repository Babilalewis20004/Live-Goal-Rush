export function LiveIndicator({ className = "bg-emerald-400" }: { className?: string }) {
  return <span className={`ls-live-dot h-1.5 w-1.5 rounded-full ${className}`} />
}

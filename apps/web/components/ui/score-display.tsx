export function ScoreDisplay({
  value,
  live,
  dim,
}: {
  value: number
  live?: boolean
  dim?: boolean
}) {
  return (
    <span
      className={[
        "w-6 text-center text-base font-bold tabular-nums",
        live ? "text-emerald-400" : dim ? "text-white/40" : "text-white",
      ].join(" ")}
    >
      {value}
    </span>
  )
}

export function AnimatedBackground() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-[#070b09]">
      {/* deep base gradient */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_10%,#0d2a1e_0%,transparent_45%),radial-gradient(circle_at_85%_80%,#0a1f3a_0%,transparent_50%)]" />

      {/* drifting color orbs */}
      <div className="ls-orb-1 absolute -left-40 top-[-10%] h-[520px] w-[520px] rounded-full bg-emerald-500/20 blur-[120px]" />
      <div className="ls-orb-2 absolute right-[-15%] top-[20%] h-[480px] w-[480px] rounded-full bg-sky-500/15 blur-[130px]" />
      <div className="ls-orb-3 absolute bottom-[-20%] left-[30%] h-[560px] w-[560px] rounded-full bg-teal-400/10 blur-[140px]" />

      {/* moving pitch lines */}
      <div
        className="ls-pitch-lines absolute left-0 right-0 top-0 opacity-[0.05]"
        style={{
          // one pattern period (160px) taller than the viewport so the translate-by-one-period loop never shows an edge
          height: "calc(100% + 160px)",
          backgroundImage:
            "repeating-linear-gradient(to bottom, transparent 0 78px, rgba(255,255,255,0.9) 78px 80px)",
          backgroundSize: "100% 160px",
        }}
      />

      {/* subtle grid texture */}
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.6) 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />

      {/* vignette */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_40%,transparent_30%,rgba(0,0,0,0.55)_100%)]" />
    </div>
  )
}

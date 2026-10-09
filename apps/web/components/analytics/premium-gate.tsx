import Link from "next/link"

const CARD = "rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.04] p-4"

/** Shown where Premium detail is withheld. The free view next to it stays useful;
 * this only explains what the upgrade adds. Withholding is done by the server -- this
 * component is just the explanation. */
export function PremiumGate({ title, items, signedIn }: { title: string; items?: string[]; signedIn: boolean }) {
  return (
    <aside className={CARD} aria-label={`${title} is a Premium feature`}>
      <h3 className="text-sm font-semibold text-white">
        <span aria-hidden>🔒 </span>
        {title}
      </h3>
      {items && items.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-white/60">
          {items.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-white/60">
        Livescores, the match centre, news and community stay free.{" "}
        <Link href={signedIn ? "/premium" : "/login?next=/premium"} className="font-medium text-emerald-300 underline-offset-2 hover:underline">
          {signedIn ? "See Premium" : "Sign in to see Premium"}
        </Link>
      </p>
    </aside>
  )
}

/** A one-line note under a free view listing what Premium would add. */
export function LockedNote({ locked, signedIn }: { locked: string[]; signedIn: boolean }) {
  if (locked.length === 0) return null
  return (
    <p className="mt-3 text-[11px] text-white/60">
      <span aria-hidden>🔒 </span>
      More detail ({locked.join(", ").replaceAll("_", " ")}) is part of{" "}
      <Link href={signedIn ? "/premium" : "/login?next=/premium"} className="text-emerald-300/80 hover:underline">
        Premium
      </Link>
      .
    </p>
  )
}

import Link from "next/link"

/** Previous / Next as real links (crawlable, work without JS). `hrefFor` maps
 * a page number to its URL, so the caller keeps its own filter parameters. */
export function Pagination({
  page,
  pageSize,
  total,
  hrefFor,
}: {
  page: number
  pageSize: number
  total: number
  hrefFor: (page: number) => string
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  const linkClass =
    "inline-flex min-h-10 items-center rounded-xl border border-white/10 bg-white/[0.03] px-4 text-xs font-medium text-white/80 hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
  const disabledClass =
    "inline-flex min-h-10 items-center rounded-xl border border-white/[0.06] px-4 text-xs font-medium text-white/25"
  return (
    <nav aria-label="Pagination" className="mt-6 flex items-center justify-between gap-3">
      {page > 1 ? (
        <Link href={hrefFor(page - 1)} rel="prev" className={linkClass}>
          ← Newer
        </Link>
      ) : (
        <span aria-disabled="true" className={disabledClass}>
          ← Newer
        </span>
      )}
      <p className="text-xs text-white/40" aria-current="page">
        Page {page} of {pages}
      </p>
      {page < pages ? (
        <Link href={hrefFor(page + 1)} rel="next" className={linkClass}>
          Older →
        </Link>
      ) : (
        <span aria-disabled="true" className={disabledClass}>
          Older →
        </span>
      )}
    </nav>
  )
}

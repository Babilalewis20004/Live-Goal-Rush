import type { Metadata } from "next"
import Link from "next/link"

import { AnimatedBackground } from "@/components/animated-background"
import { ArticleCard } from "@/components/news/article-card"
import { EmptyState } from "@/components/ui/empty-state"
import { ErrorState } from "@/components/ui/error-state"
import { Pagination } from "@/components/ui/pagination"
import { api } from "@/lib/api"
import { newsHref } from "@/lib/news"
import { pageMetadata } from "@/lib/seo"

export const dynamic = "force-dynamic"
const PAGE_SIZE = 12

type SearchParams = Promise<{ category?: string; tag?: string; page?: string }>

export async function generateMetadata({ searchParams }: { searchParams: SearchParams }): Promise<Metadata> {
  const { category, tag, page } = await searchParams
  const base = pageMetadata({
    title: "Football News",
    description: "The latest football news, transfers, match reports and analysis from the leagues you follow.",
    path: "/news",
  })
  // Filtered and paged variants stay out of the index; the canonical always
  // points at the main listing, so there is one indexable /news.
  const variant = Boolean(category || tag || (page && page !== "1"))
  return variant ? { ...base, robots: { index: false, follow: true } } : base
}

const CHIP = "inline-flex min-h-9 items-center rounded-full border px-3.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

export default async function NewsPage({ searchParams }: { searchParams: SearchParams }) {
  const { category, tag, page: rawPage } = await searchParams
  const page = Math.max(1, Number.parseInt(rawPage ?? "1", 10) || 1)

  const [categories, listing] = await Promise.all([
    api.getArticleCategories().catch(() => []),
    api.getArticles({ page, pageSize: PAGE_SIZE, category, tag }).catch(() => null),
  ])
  const filtered = Boolean(category || tag)
  const [lead, ...rest] = listing?.items ?? []
  const showLead = page === 1 && !filtered && lead

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>
        <h1 className="mb-1 mt-4 text-xl font-bold text-white">Football News</h1>
        {tag && (
          <p className="mb-2 text-xs text-white/50">
            Tagged <strong className="text-white/80">#{tag}</strong> ·{" "}
            <Link href={newsHref({ category })} className="underline hover:text-white">
              clear
            </Link>
          </p>
        )}

        {categories.length > 0 && (
          <nav aria-label="News categories" className="-mx-4 mb-5 mt-3 overflow-x-auto px-4">
            <ul className="flex gap-2 pb-1">
              <li>
                <Link
                  href="/news"
                  aria-current={!category ? "page" : undefined}
                  className={`${CHIP} ${!category ? "border-emerald-400/60 bg-emerald-400/15 text-white" : "border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.07]"}`}
                >
                  All
                </Link>
              </li>
              {categories.map((c) => (
                <li key={c.id} className="shrink-0">
                  <Link
                    href={newsHref({ category: c.slug, tag })}
                    aria-current={category === c.slug ? "page" : undefined}
                    className={`${CHIP} ${category === c.slug ? "border-emerald-400/60 bg-emerald-400/15 text-white" : "border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.07]"}`}
                  >
                    {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        )}

        {listing === null && <ErrorState message="News is unavailable right now. Please try again shortly." />}
        {listing !== null && listing.items.length === 0 && (
          <EmptyState message={filtered ? "No articles match this filter yet." : "No news published yet."} />
        )}

        {listing !== null && listing.items.length > 0 && (
          <div className="space-y-3">
            {showLead && <ArticleCard article={lead} variant="hero" />}
            <ul className="space-y-3">
              {(showLead ? rest : listing.items).map((article) => (
                <li key={article.id}>
                  <ArticleCard article={article} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {listing !== null && (
          <Pagination
            page={listing.page}
            pageSize={listing.page_size}
            total={listing.total}
            hrefFor={(p) => newsHref({ category, tag, page: p })}
          />
        )}
      </div>
    </main>
  )
}

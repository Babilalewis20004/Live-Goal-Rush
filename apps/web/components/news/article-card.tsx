import Image from "next/image"
import Link from "next/link"

import { formatArticleDate, relationLabel } from "@/lib/news"
import type { ArticleSummary } from "@/types/api"

type Variant = "hero" | "default" | "compact"

/** One article in a list. The whole card is a single link (the headline), so
 * keyboard and screen-reader users meet one stop per article; the image is
 * decorative to them because the headline already names it. State is always
 * text (category, "About this match"), never colour alone. */
export function ArticleCard({ article, variant = "default" }: { article: ArticleSummary; variant?: Variant }) {
  const relation = relationLabel(article.relation)
  const meta = [article.category?.name, formatArticleDate(article.published_at)].filter(Boolean).join(" · ")

  if (variant === "compact") {
    return (
      <article className="relative px-4 py-3 transition-colors hover:bg-white/[0.04] focus-within:bg-white/[0.04]">
        <h3 className="text-sm font-medium leading-snug text-white">
          <Link href={`/article/${article.slug}`} className="after:absolute after:inset-0 focus-visible:outline-none">
            {article.title}
          </Link>
        </h3>
        <p className="mt-1 text-[11px] text-white/40">{[relation, meta].filter(Boolean).join(" · ")}</p>
        {article.reason && <p className="mt-0.5 text-[10px] text-white/30">Suggested: {article.reason.toLowerCase()}</p>}
      </article>
    )
  }

  const hero = variant === "hero"
  return (
    <article
      className={[
        "group relative overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md transition-colors",
        "hover:bg-white/[0.06] focus-within:ring-2 focus-within:ring-emerald-400/70",
        hero ? "" : "flex gap-3 p-3",
      ].join(" ")}
    >
      {article.featured_image_url && (
        <div
          className={
            hero
              ? "relative aspect-[16/9] w-full bg-white/[0.04]"
              : "relative h-20 w-28 shrink-0 overflow-hidden rounded-xl bg-white/[0.04] sm:h-24 sm:w-36"
          }
        >
          <Image
            src={article.featured_image_url}
            alt=""
            fill
            sizes={hero ? "(min-width: 768px) 672px, 100vw" : "144px"}
            className="object-cover"
            loading={hero ? "eager" : "lazy"}
            unoptimized
          />
        </div>
      )}
      <div className={hero ? "p-4" : "min-w-0 flex-1"}>
        <p className="text-[11px] font-medium uppercase tracking-wide text-emerald-300/80">
          {relation ?? article.category?.name ?? "News"}
        </p>
        <h3 className={`${hero ? "mt-1 text-lg" : "mt-0.5 text-sm"} font-semibold leading-snug text-white`}>
          <Link href={`/article/${article.slug}`} className="after:absolute after:inset-0 focus-visible:outline-none">
            {article.title}
          </Link>
        </h3>
        {article.excerpt && (
          <p className={`mt-1 text-white/55 ${hero ? "line-clamp-3 text-sm" : "line-clamp-2 text-xs"}`}>{article.excerpt}</p>
        )}
        <p className="mt-1.5 text-[11px] text-white/40">
          {[meta, article.author_name && `By ${article.author_name}`].filter(Boolean).join(" · ")}
        </p>
        {article.reason && <p className="mt-0.5 text-[10px] text-white/30">Suggested: {article.reason.toLowerCase()}</p>}
      </div>
    </article>
  )
}

/** Renders an article body. `html` is already sanitized by the API against an
 * allow-list (tags, attributes and URL schemes) before it is stored, so it is
 * safe to inject; nothing here (or anywhere else) renders unsanitized
 * editor HTML. Styling is applied to descendants because the markup is data,
 * not components. */
export function ArticleBody({ html }: { html: string }) {
  return (
    <div
      className={[
        "text-[15px] leading-relaxed text-white/80",
        "[&_p]:mb-4 [&_h2]:mb-3 [&_h2]:mt-8 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-white",
        "[&_h3]:mb-2 [&_h3]:mt-6 [&_h3]:text-base [&_h3]:font-semibold [&_h3]:text-white",
        "[&_h4]:mb-2 [&_h4]:mt-5 [&_h4]:font-semibold [&_h4]:text-white",
        "[&_a]:text-emerald-300 [&_a]:underline [&_a]:underline-offset-2 hover:[&_a]:text-emerald-200",
        "[&_ul]:mb-4 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:mb-4 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:mb-1",
        "[&_blockquote]:mb-4 [&_blockquote]:border-l-2 [&_blockquote]:border-emerald-400/60 [&_blockquote]:pl-4 [&_blockquote]:italic",
        "[&_img]:my-4 [&_img]:h-auto [&_img]:max-w-full [&_img]:rounded-xl [&_hr]:my-6 [&_hr]:border-white/10",
      ].join(" ")}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

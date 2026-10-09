import { notFound } from "next/navigation"

import { ArticleEditor } from "@/components/editor/article-editor"

export default async function EditArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const articleId = Number((await params).id)
  if (!Number.isInteger(articleId) || articleId < 1) notFound()
  return <ArticleEditor articleId={articleId} />
}

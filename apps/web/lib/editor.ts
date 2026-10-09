import { fromLocalInput, toLocalInput } from "@/lib/editorial"
import type {
  ArticleAdminOut,
  ArticleInput,
  ArticleStatus,
  CompetitionOut,
  MatchSummary,
  PlayerOut,
  TeamOut,
} from "@/types/api"

export const STATUS_LABEL: Record<ArticleStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  scheduled: "Scheduled",
  published: "Published",
  archived: "Archived",
}

export interface LinkedEntities {
  teams: TeamOut[]
  players: PlayerOut[]
  competitions: CompetitionOut[]
  matches: MatchSummary[]
}

export interface GalleryField {
  media_id: number
  caption: string
  thumb_url: string
  alt: string
}

export interface FeaturedMediaField {
  id: number
  url: string
}

export interface EditorFields {
  title: string
  excerpt: string
  content: string
  imageUrl: string
  imageAlt: string
  categoryId: number | null
  tags: string
  featured: boolean
  entities: LinkedEntities
  /** An uploaded image used as the featured image (takes precedence over `imageUrl`). */
  featuredMedia: FeaturedMediaField | null
  gallery: GalleryField[]
  /** datetime-local values in the editor's own time zone; sent as ISO. */
  publishAt: string
  unpublishAt: string
}

export const EMPTY_FIELDS: EditorFields = {
  title: "",
  excerpt: "",
  content: "",
  imageUrl: "",
  imageAlt: "",
  categoryId: null,
  tags: "",
  featured: false,
  entities: { teams: [], players: [], competitions: [], matches: [] },
  featuredMedia: null,
  gallery: [],
  publishAt: "",
  unpublishAt: "",
}

/** "Real Madrid, transfer ,real madrid" -> ["Real Madrid", "transfer"]: trimmed,
 * case-insensitively de-duplicated, at most 10 of at most 50 characters (the
 * API's limits), so the form never sends something the server will reject. */
export function parseTags(text: string): string[] {
  const seen = new Set<string>()
  const tags: string[] = []
  for (const raw of text.split(",")) {
    const tag = raw.replace(/\s+/g, " ").trim().slice(0, 50)
    const key = tag.toLowerCase()
    if (!tag || seen.has(key)) continue
    seen.add(key)
    tags.push(tag)
    if (tags.length === 10) break
  }
  return tags
}

export function fieldsFromArticle(article: ArticleAdminOut): EditorFields {
  return {
    title: article.title,
    excerpt: article.excerpt,
    content: article.content,
    imageUrl: article.featured_image_url ?? "",
    imageAlt: article.featured_image_alt ?? "",
    categoryId: article.category?.id ?? null,
    tags: article.tags.map((t) => t.name).join(", "),
    featured: article.is_featured,
    entities: {
      teams: article.teams,
      players: article.players,
      competitions: article.competitions,
      matches: article.matches,
    },
    featuredMedia:
      article.featured_media_id && article.featured_image_url
        ? { id: article.featured_media_id, url: article.featured_image_url }
        : null,
    gallery: article.gallery.map((g) => ({ media_id: g.media_id, caption: g.caption, thumb_url: g.thumb_url, alt: g.alt })),
    publishAt: toLocalInput(article.publish_at),
    unpublishAt: toLocalInput(article.unpublish_at),
  }
}

/** The API payload for the form's current state. Empty optional fields become
 * explicit `null`s so clearing the image or category actually clears it. */
export function buildInput(fields: EditorFields, opts: { includeSchedule?: boolean } = {}): ArticleInput {
  return {
    title: fields.title.trim(),
    excerpt: fields.excerpt.trim(),
    content: fields.content,
    // an uploaded image wins; otherwise the typed address (or none)
    featured_image_url: fields.featuredMedia ? undefined : fields.imageUrl.trim() || null,
    featured_image_alt: fields.featuredMedia || fields.imageUrl.trim() ? fields.imageAlt.trim() || null : null,
    featured_media_id: fields.featuredMedia?.id ?? null,
    gallery: fields.gallery.map((g) => ({ media_id: g.media_id, caption: g.caption })),
    category_id: fields.categoryId,
    tags: parseTags(fields.tags),
    team_ids: fields.entities.teams.map((t) => t.id),
    player_ids: fields.entities.players.map((p) => p.id),
    competition_ids: fields.entities.competitions.map((c) => c.id),
    match_ids: fields.entities.matches.map((m) => m.id),
    is_featured: fields.featured,
    // Only editors may schedule; sending these as an author would be refused.
    ...(opts.includeSchedule
      ? { publish_at: fromLocalInput(fields.publishAt), unpublish_at: fromLocalInput(fields.unpublishAt) }
      : {}),
  }
}

/** Why the form can't be saved yet (null = it can). */
export function validateFields(fields: EditorFields): string | null {
  if (fields.title.trim().length < 3) return "Give the article a title of at least 3 characters."
  if (fields.imageUrl.trim() && !/^https?:\/\//i.test(fields.imageUrl.trim())) {
    return "The featured image must be an http(s) address."
  }
  return null
}

/** Why it can't be published yet (null = it can). */
export function validatePublish(fields: EditorFields): string | null {
  const base = validateFields(fields)
  if (base) return base
  const text = fields.content.replace(/<[^>]*>/g, "").trim()
  if (!text) return "Add some content before publishing."
  return null
}

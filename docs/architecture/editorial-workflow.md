# Editorial workflow (Phase 6a)

Articles move through `DRAFT → IN_REVIEW → (SCHEDULED →) PUBLISHED → ARCHIVED`. The server is the only authority:
`ArticleService` checks the caller's role and ownership on every transition; the web and mobile editors mirror the
rules (`availableActions`) only to decide which buttons to show.

## Roles (`users.role`, granted with `python -m app.cli set-role`)

| Role | Can |
|---|---|
| `user` | nothing editorial |
| `author` | create drafts; edit **their own** drafts and articles that were sent back; submit for review; withdraw their own submission; upload media |
| `editor` | everything an author can, plus: see everything that has left draft; edit in-review articles; **approve** (publish or schedule), **request changes** (with a note), publish, schedule, unpublish, archive; create polls; moderate comments |
| `admin` | everything, including other people's drafts and suspending accounts |

An author can never publish or schedule: even a direct API call with `status=published` is refused.

## Transitions

| Action | From | To | Who |
|---|---|---|---|
| `POST /editor/articles/{id}/submit` | draft | in_review | owner/admin |
| `…/withdraw` | in_review | draft | owner/editor/admin |
| `…/approve` (optionally `publish_at`) | in_review | published, or scheduled if `publish_at` is in the future | editor/admin |
| `…/reject` {note} | in_review | draft (note shown to the author) | editor/admin |
| `…/publish` | draft/in_review/scheduled | published | editor/admin |
| `…/schedule` {publish_at} | draft/in_review | scheduled | editor/admin |
| `…/unpublish` | published/scheduled | draft | editor/admin |
| `…/archive` | any | archived | editor/admin |

## Scheduled publishing

`publish_at` / `unpublish_at` are stored on the article. A Celery beat task (`publish_scheduled_articles`, every
60 s) runs one atomic statement — `UPDATE articles SET status = PUBLISHED, published_at = coalesce(publish_at, now())
WHERE status = SCHEDULED AND publish_at <= now() RETURNING id` — then a second to archive published articles past
`unpublish_at`. Because the transition is a conditional UPDATE, concurrent or repeated runs publish each article
exactly once. Each automatic change records a `SCHEDULED` revision with no human editor. Newly published articles
trigger the existing article notifications and the author's "your article is live" notice.

## Revisions

Every create/update/status change appends an immutable full JSONB snapshot (`article_revisions`, unique
`(article_id, version)`) in the same transaction as the change. The editor can list versions, view one, **compare
any two** (field-level diff plus a text diff of the body) and **restore** one — restoring creates a *new* version
rather than rewriting history. Access follows the article's visibility rules.

## Notifications

Submitted → editors/admins (not the submitter); approved/published/scheduled/changes-requested → the author. Kind
`editorial_updates` (default on), deduplicated.

## Editors on web and mobile

Web: `/editor` (list with status filters), the article editor (media library, revisions panel, schedule, preview),
`/editor/media`, `/editor/polls`, `/editor/moderation`. Mobile: editor list and editor screen (draft, edit, upload
from the photo library, preview of the last saved version, submit/approve/request changes by role). The mobile app
has no revision comparison UI (the API supports it).

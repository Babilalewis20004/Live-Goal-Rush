# Media platform (Phase 6a)

Editors and authors upload images; the platform validates them, re-encodes them, stores several sizes in
object storage and serves them through the API (or a CDN). No client ever sees a filesystem path.

## Storage

`StorageBackend` (`services/storage.py`) has three implementations chosen by `MEDIA_STORAGE_BACKEND`:

| Backend | Use |
|---|---|
| `s3` | S3, Cloudflare R2 or MinIO (boto3, run in threads). `S3_ENDPOINT_URL`, `S3_BUCKET`, keys. The bucket is created on start-up if missing (MinIO in Docker Compose). |
| `local` | A directory (`MEDIA_LOCAL_ROOT`) — development without MinIO. |
| `memory` | The test suite. |

Object keys are generated from random ids by the server and validated; a user-supplied name is only ever stored as
a display label, never as part of a key or path.

## Upload pipeline (`services/media_service.py`)

`POST /api/v1/editor/media` (author/editor/admin; 20 uploads/min and 200/day per user):

1. Read at most `MEDIA_MAX_BYTES` (5 MB) — larger is rejected before decoding.
2. **Decode with Pillow and judge the bytes, not the declared type or filename.** Only JPEG, PNG, WebP and GIF
   (animated: first frame) are accepted; SVG and everything else is refused. Dimensions must be between 64 px and
   8000 px per side and under 40 megapixels (decompression-bomb guard).
3. **Re-encode to WebP** (quality 82). This strips EXIF/GPS and any payload appended after the image data; what is
   stored is a fresh encoding, not the upload.
4. Produce variants: `original` (≤ 4096 px), `large` (1600), `medium` (800), `thumb` (320), keeping aspect ratio.
5. Store the variants, then the `media` + `media_variants` rows. Alt text (the image's own, else the article title) is used when an image
   is a featured image or in a gallery. Images can be organised into folders, renamed and deleted (deleting an
   image used by an article or player is refused).

CPU-bound work runs in a thread (`asyncio.to_thread`) so uploads do not block the event loop.

## Delivery

`GET /api/v1/media/{public_id}/{variant}` streams the object with
`Cache-Control: public, max-age=31536000, immutable`, a strong `ETag` (conditional requests get `304`),
`X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'; sandbox`. Variant ids are
immutable (editing an image makes a new one), which is what makes the year-long cache safe. If
`MEDIA_PUBLIC_BASE_URL` is set (a CDN or public bucket) URLs point there instead.

## Using media

Articles reference `featured_media_id` and an ordered `gallery`; the article API returns resolved URLs. The web
editor has a media library and picker; the mobile editor uploads from the photo library (`expo-image-picker`,
permission requested only when asked, size/type checked before upload). Article HTML may only embed images from
`ARTICLE_IMAGE_ALLOWED_HOSTS` or this platform's own media URLs.

## Security summary

Authenticated, role-checked, rate-limited uploads; content judged on bytes; polyglot/EXIF payloads removed by
re-encoding; size/dimension/pixel limits; server-generated keys; no directory traversal surface; sandboxed,
non-sniffable responses. Not included: antivirus scanning and perceptual-hash moderation of uploaded images.

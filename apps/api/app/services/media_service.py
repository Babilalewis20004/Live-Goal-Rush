"""Image upload, validation, optimisation and delivery (Phase 6).

Trust model: nothing the client says about a file is believed. The declared
content type and filename are ignored for decisions; Pillow decodes the bytes
and *its* verdict on format and dimensions is what counts. The image is then
**re-encoded** (WebP), which strips EXIF/GPS and any payload appended to a
valid image, so what is stored and served is always something this code
produced.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import secrets
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging_config import log_event
from app.core.redis_client import RedisService
from app.models.article import Article, ArticleGalleryItem
from app.models.media import Media, MediaFolder, MediaVariant
from app.models.player import Player
from app.models.user import User
from app.schemas.media import FolderOut, GalleryImage, MediaOut, MediaVariantOut
from app.services.metrics import metrics
from app.services.storage import StorageBackend, StorageError, StorageNotFound

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
# name -> longest side. `original` is the upload re-encoded (capped), the rest are
# progressively smaller renditions.
VARIANT_SIDES: tuple[tuple[str, int], ...] = (("original", 4096), ("large", 1600), ("medium", 800), ("thumb", 320))
VARIANT_NAMES = tuple(name for name, _ in VARIANT_SIDES)
_WEBP_QUALITY = 82
_PUBLIC_ID = re.compile(r"^[0-9a-f]{24}$")


class MediaError(Exception):
    status_code = 422


class MediaValidationError(MediaError):
    status_code = 422


class MediaTooLargeError(MediaError):
    status_code = 413


class MediaNotFoundError(MediaError):
    status_code = 404


class MediaPermissionError(MediaError):
    status_code = 403


class MediaInUseError(MediaError):
    status_code = 409


@dataclass
class ProcessedVariant:
    name: str
    data: bytes
    width: int
    height: int


@dataclass
class ProcessedImage:
    width: int
    height: int
    variants: list[ProcessedVariant]


def sanitize_filename(name: str | None) -> str:
    """For display only (it is never used to build a key or path)."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[^\w.\- ]+", "", base).strip(" .")
    return base[:120]


def _encode(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=_WEBP_QUALITY, method=4)
    return out.getvalue()


def process_image(data: bytes) -> ProcessedImage:
    """Validate and produce every variant. CPU-bound: call via `asyncio.to_thread`."""
    if not data:
        raise MediaValidationError("The file is empty.")
    if len(data) > settings.media_max_bytes:
        raise MediaTooLargeError(f"The file is larger than {settings.media_max_bytes // (1024 * 1024)} MB.")

    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = settings.media_max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # warning -> error
            try:
                probe = Image.open(io.BytesIO(data))
                fmt = probe.format
                width, height = probe.size  # header only: reject before decoding pixels
                if fmt not in ALLOWED_FORMATS:
                    raise MediaValidationError("Only JPEG, PNG, WebP and GIF images are accepted.")
                if min(width, height) < settings.media_min_side:
                    raise MediaValidationError(f"The image is too small (minimum {settings.media_min_side}px per side).")
                if max(width, height) > settings.media_max_side or width * height > settings.media_max_pixels:
                    raise MediaValidationError(
                        f"The image is too large ({width}x{height}); the limit is {settings.media_max_side}px per side."
                    )
                probe.seek(0)  # animated GIF/WebP: first frame only
                img = ImageOps.exif_transpose(probe)  # honour rotation, then metadata is dropped on re-encode
                img.load()
            except MediaError:
                raise
            except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError, ValueError, EOFError) as exc:
                raise MediaValidationError("The file is not a valid image.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    width, height = img.size

    variants: list[ProcessedVariant] = []
    for name, side in VARIANT_SIDES:
        rendition = img.copy()
        if max(rendition.size) > side:
            rendition.thumbnail((side, side), Image.Resampling.LANCZOS)
        variants.append(ProcessedVariant(name, _encode(rendition), *rendition.size))
    return ProcessedImage(width, height, variants)


def media_url(public_id: str, variant: str, storage_key: str | None = None) -> str:
    if settings.media_public_base_url and storage_key:
        return f"{settings.media_public_base_url.rstrip('/')}/{storage_key}"
    return f"{settings.public_api_url.rstrip('/')}/api/v1/media/{public_id}/{variant}"


def to_out(media: Media) -> MediaOut:
    variants = {
        v.name: MediaVariantOut(
            url=media_url(media.public_id, v.name, v.storage_key), width=v.width, height=v.height, size_bytes=v.size_bytes
        )
        for v in media.variants
    }
    large = variants.get("large") or next(iter(variants.values()))
    thumb = variants.get("thumb") or large
    return MediaOut(
        id=media.id,
        folder_id=media.folder_id,
        filename=media.original_filename,
        alt_text=media.alt_text,
        width=media.width,
        height=media.height,
        size_bytes=media.size_bytes,
        created_at=media.created_at,
        url=large.url,
        thumb_url=thumb.url,
        variants=variants,
    )


def to_gallery_image(item: ArticleGalleryItem) -> GalleryImage:
    out = to_out(item.media)
    return GalleryImage(
        media_id=item.media_id,
        url=out.url,
        thumb_url=out.thumb_url,
        alt=item.caption or item.media.alt_text or item.media.original_filename,
        width=out.variants["large"].width if "large" in out.variants else item.media.width,
        height=out.variants["large"].height if "large" in out.variants else item.media.height,
        caption=item.caption,
    )


class MediaService:
    def __init__(self, db: AsyncSession, storage: StorageBackend, redis: RedisService | None = None) -> None:
        self.db = db
        self.storage = storage
        self.redis = redis

    # -- permissions ------------------------------------------------------------

    @staticmethod
    def _can_see_all(user: User) -> bool:
        return user.role.value in ("editor", "admin")

    async def _get_for(self, user: User, media_id: int) -> Media:
        media = await self.db.scalar(select(Media).where(Media.id == media_id).options(selectinload(Media.variants)))
        if media is None:
            raise MediaNotFoundError("Media not found")
        if not self._can_see_all(user) and media.uploader_id != user.id:
            raise MediaPermissionError("You can only use your own uploads.")
        return media

    async def get_for_use(self, user: User, media_id: int) -> Media:
        """For linking from an article/player: must exist and be usable by `user`."""
        return await self._get_for(user, media_id)

    # -- upload -----------------------------------------------------------------

    async def _check_quota(self, user: User) -> None:
        if self.redis is None:
            return
        try:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            count = await self.redis.incr(f"media:uploads:{user.id}:{day}", ttl_seconds=86400)
        except Exception:
            return  # fail open, like every other limiter here
        if count > settings.media_uploads_per_day:
            raise MediaTooLargeError("Daily upload limit reached. Try again tomorrow.")

    async def upload(
        self, user: User, *, filename: str | None, data: bytes, folder_id: int | None = None, alt_text: str = ""
    ) -> Media:
        if folder_id is not None and await self.db.get(MediaFolder, folder_id) is None:
            raise MediaValidationError("Unknown folder")
        try:
            processed = await asyncio.to_thread(process_image, data)
        except MediaError:
            metrics.media_upload_rejected()
            log_event(logger, "media_upload_rejected", user_id=user.id, size_bytes=len(data))
            raise
        await self._check_quota(user)

        public_id = secrets.token_hex(12)
        written: list[str] = []
        try:
            for variant in processed.variants:
                key = f"media/{public_id}/{variant.name}.webp"
                await self.storage.put(key, variant.data, "image/webp")
                written.append(key)
            media = Media(
                public_id=public_id,
                folder_id=folder_id,
                uploader_id=user.id,
                original_filename=sanitize_filename(filename),
                alt_text=alt_text.strip()[:200],
                width=processed.width,
                height=processed.height,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            media.variants = [
                MediaVariant(
                    name=v.name,
                    storage_key=f"media/{public_id}/{v.name}.webp",
                    content_type="image/webp",
                    width=v.width,
                    height=v.height,
                    size_bytes=len(v.data),
                    etag=hashlib.sha256(v.data).hexdigest()[:32],
                )
                for v in processed.variants
            ]
            self.db.add(media)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            for key in written:  # never leave orphaned objects behind
                try:
                    await self.storage.delete(key)
                except StorageError:
                    logger.warning("Could not clean up %s after a failed upload", key)
            raise
        metrics.media_uploaded()
        log_event(logger, "media_upload", media_id=media.id, user_id=user.id, size_bytes=len(data), width=media.width, height=media.height)
        return await self.db.scalar(select(Media).where(Media.id == media.id).options(selectinload(Media.variants)).execution_options(populate_existing=True))

    # -- library ------------------------------------------------------------------

    async def list_media(self, user: User, *, folder_id: int | None, page: int, page_size: int) -> tuple[list[Media], int]:
        clauses = []
        if not self._can_see_all(user):
            clauses.append(Media.uploader_id == user.id)
        if folder_id is not None:
            clauses.append(Media.folder_id == folder_id)
        total = (await self.db.execute(select(func.count()).select_from(Media).where(*clauses))).scalar_one()
        rows = (
            await self.db.execute(
                select(Media).where(*clauses).options(selectinload(Media.variants))
                .order_by(Media.created_at.desc(), Media.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def update(self, user: User, media_id: int, *, alt_text: str | None, folder_id: int | None, move_to_root: bool) -> Media:
        media = await self._get_for(user, media_id)
        if alt_text is not None:
            media.alt_text = alt_text.strip()[:200]
        if move_to_root:
            media.folder_id = None
        elif folder_id is not None:
            if await self.db.get(MediaFolder, folder_id) is None:
                raise MediaValidationError("Unknown folder")
            media.folder_id = folder_id
        await self.db.commit()
        return media

    async def delete(self, user: User, media_id: int) -> None:
        media = await self._get_for(user, media_id)
        in_use = (
            await self.db.scalar(select(Article.id).where(Article.featured_media_id == media.id).limit(1))
            or await self.db.scalar(select(ArticleGalleryItem.article_id).where(ArticleGalleryItem.media_id == media.id).limit(1))
            or await self.db.scalar(select(Player.id).where(Player.photo_url.like(f"%/media/{media.public_id}/%")).limit(1))
        )
        if in_use:
            raise MediaInUseError("This image is used by an article or player; remove it there first.")
        keys = [v.storage_key for v in media.variants]
        public_id = media.public_id
        await self.db.delete(media)
        await self.db.commit()
        for key in keys:
            try:
                await self.storage.delete(key)
            except StorageError:
                logger.warning("Could not delete %s", key)
        if self.redis is not None:
            try:
                await self.redis.delete(*[f"media:meta:{public_id}:{n}" for n in VARIANT_NAMES])
            except Exception:
                pass
        log_event(logger, "media_delete", media_id=media_id, user_id=user.id)

    # -- folders ------------------------------------------------------------------

    async def list_folders(self) -> list[FolderOut]:
        counts = dict((await self.db.execute(select(Media.folder_id, func.count()).where(Media.folder_id.is_not(None)).group_by(Media.folder_id))).all())
        folders = (await self.db.execute(select(MediaFolder).order_by(MediaFolder.name))).scalars().all()
        return [FolderOut(id=f.id, name=f.name, parent_id=f.parent_id, media_count=counts.get(f.id, 0)) for f in folders]

    async def create_folder(self, user: User, name: str, parent_id: int | None) -> FolderOut:
        name = " ".join(name.split())
        if not name:
            raise MediaValidationError("Folder needs a name")
        if parent_id is not None and await self.db.get(MediaFolder, parent_id) is None:
            raise MediaValidationError("Unknown parent folder")
        exists = await self.db.scalar(
            select(MediaFolder.id).where(MediaFolder.name == name, MediaFolder.parent_id.is_(None) if parent_id is None else MediaFolder.parent_id == parent_id)
        )
        if exists:
            raise MediaValidationError("A folder with that name already exists here")
        folder = MediaFolder(name=name, parent_id=parent_id, created_by=user.id)
        self.db.add(folder)
        await self.db.commit()
        return FolderOut(id=folder.id, name=folder.name, parent_id=folder.parent_id, media_count=0)

    async def delete_folder(self, folder_id: int) -> None:
        folder = await self.db.get(MediaFolder, folder_id)
        if folder is None:
            raise MediaNotFoundError("Folder not found")
        has_media = await self.db.scalar(select(Media.id).where(Media.folder_id == folder_id).limit(1))
        has_children = await self.db.scalar(select(MediaFolder.id).where(MediaFolder.parent_id == folder_id).limit(1))
        if has_media or has_children:
            raise MediaInUseError("Only empty folders can be deleted.")
        await self.db.delete(folder)
        await self.db.commit()

    # -- delivery -----------------------------------------------------------------

    async def serve(self, public_id: str, variant: str) -> tuple[bytes, str, str]:
        """(bytes, content_type, etag) for a public image. Metadata is cached in
        Redis so a hit costs one Redis read plus the storage read -- no database."""
        if not _PUBLIC_ID.match(public_id) or variant not in VARIANT_NAMES:
            raise MediaNotFoundError("Not found")
        key = f"media:meta:{public_id}:{variant}"
        meta = None
        if self.redis is not None:
            try:
                meta = await self.redis.get(key)
            except Exception:
                meta = None
        if meta is None:
            row = await self.db.execute(
                select(MediaVariant.storage_key, MediaVariant.content_type, MediaVariant.etag)
                .join(Media, Media.id == MediaVariant.media_id)
                .where(Media.public_id == public_id, MediaVariant.name == variant)
            )
            found = row.first()
            if found is None:
                raise MediaNotFoundError("Not found")
            meta = {"key": found[0], "content_type": found[1], "etag": found[2]}
            if self.redis is not None:
                try:
                    await self.redis.set(key, meta, ttl_seconds=3600)
                except Exception:
                    pass
        try:
            data = await self.storage.get(meta["key"])
        except StorageNotFound as exc:
            raise MediaNotFoundError("Not found") from exc
        return data, meta["content_type"], meta["etag"]

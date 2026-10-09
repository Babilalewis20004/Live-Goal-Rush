"""Media API: uploads, the media library, and public image delivery."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status

from app.api.deps import EditorDep, MediaServiceDep, ReviewerDep
from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.db.session import get_db
from app.models.player import Player
from app.schemas.common import Page
from app.schemas.media import FolderIn, FolderOut, MediaOut, MediaUpdate, PlayerPhotoIn
from app.services.media_service import MediaError, MediaTooLargeError, to_out
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
public_router = APIRouter()

_READ_CHUNK = 64 * 1024


def _http(exc: MediaError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _read_limited(file: UploadFile) -> bytes:
    """Read at most the configured limit (+1 byte to detect overflow), so an
    oversized upload is refused without being buffered in full."""
    limit = settings.media_max_bytes
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise MediaTooLargeError(f"The file is larger than {limit // (1024 * 1024)} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "",
    response_model=MediaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limiter("media-upload", settings.media_uploads_per_minute, 60))],
)
async def upload_media(
    user: EditorDep,
    service: MediaServiceDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG, WebP or GIF, up to the configured size")],
    folder_id: Annotated[int | None, Form()] = None,
    alt_text: Annotated[str, Form(max_length=200)] = "",
) -> MediaOut:
    try:
        data = await _read_limited(file)
        media = await service.upload(user, filename=file.filename, data=data, folder_id=folder_id, alt_text=alt_text)
    except MediaError as exc:
        raise _http(exc) from exc
    return to_out(media)


@router.get("", response_model=Page[MediaOut])
async def list_media(
    user: EditorDep,
    service: MediaServiceDep,
    folder_id: Annotated[int | None, Query(ge=1)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> Page[MediaOut]:
    items, total = await service.list_media(user, folder_id=folder_id, page=page, page_size=page_size)
    return Page(items=[to_out(m) for m in items], total=total, page=page, page_size=page_size)


@router.get("/folders", response_model=list[FolderOut])
async def list_folders(user: EditorDep, service: MediaServiceDep) -> list[FolderOut]:
    return await service.list_folders()


@router.post("/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(payload: FolderIn, user: EditorDep, service: MediaServiceDep) -> FolderOut:
    try:
        return await service.create_folder(user, payload.name, payload.parent_id)
    except MediaError as exc:
        raise _http(exc) from exc


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(folder_id: int, user: ReviewerDep, service: MediaServiceDep) -> None:
    try:
        await service.delete_folder(folder_id)
    except MediaError as exc:
        raise _http(exc) from exc


@router.patch("/{media_id}", response_model=MediaOut)
async def update_media(media_id: int, payload: MediaUpdate, user: EditorDep, service: MediaServiceDep) -> MediaOut:
    try:
        media = await service.update(
            user, media_id, alt_text=payload.alt_text, folder_id=payload.folder_id, move_to_root=payload.move_to_root
        )
    except MediaError as exc:
        raise _http(exc) from exc
    return to_out(media)


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(media_id: int, user: EditorDep, service: MediaServiceDep) -> None:
    try:
        await service.delete(user, media_id)
    except MediaError as exc:
        raise _http(exc) from exc


@router.put("/players/{player_id}/photo", response_model=MediaOut | None)
async def set_player_photo(
    player_id: int,
    payload: PlayerPhotoIn,
    user: ReviewerDep,
    service: MediaServiceDep,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Editors can attach an uploaded image as a player's photo (or clear it)."""
    player = await db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    if payload.media_id is None:
        player.photo_url = None
        await db.commit()
        return None
    try:
        media = await service.get_for_use(user, payload.media_id)
    except MediaError as exc:
        raise _http(exc) from exc
    out = to_out(media)
    player.photo_url = out.variants["medium"].url if "medium" in out.variants else out.url
    await db.commit()
    return out


# -- public delivery ----------------------------------------------------------------------------


@public_router.get("/{public_id}/{variant}", include_in_schema=True)
async def serve_media(public_id: str, variant: str, request: Request, service: MediaServiceDep) -> Response:
    """The image bytes. Immutable and long-cached: a given `public_id/variant` never
    changes (a replaced image gets a new id), so browsers and CDNs can keep it for
    a year, and `ETag` / `If-None-Match` answers revalidation with a 304."""
    try:
        data, content_type, etag = await service.serve(public_id, variant)
    except MediaError as exc:
        raise _http(exc) from exc
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": f'"{etag}"',
        "X-Content-Type-Options": "nosniff",
        # An uploaded image should only ever be displayed, never executed or framed as a document.
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }
    if request.headers.get("if-none-match", "").strip('"') == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=content_type, headers=headers)


from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MediaVariantOut(BaseModel):
    url: str
    width: int
    height: int
    size_bytes: int


class MediaOut(BaseModel):
    """What clients get: ids, dimensions and URLs -- never a storage key or path."""

    id: int
    folder_id: int | None
    filename: str
    alt_text: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime
    url: str
    """The `large` variant -- what an article's featured image uses."""
    thumb_url: str
    variants: dict[str, MediaVariantOut]


class MediaUpdate(BaseModel):
    alt_text: str | None = Field(default=None, max_length=200)
    folder_id: int | None = None
    move_to_root: bool = False
    """`folder_id: null` is ambiguous in a PATCH body, so moving out of a folder is explicit."""


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = None


class FolderOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    media_count: int = 0


class GalleryImage(BaseModel):
    media_id: int
    url: str
    thumb_url: str
    alt: str
    width: int
    height: int
    caption: str = ""


class GalleryItemIn(BaseModel):
    media_id: int
    caption: str = Field(default="", max_length=200)


class PlayerPhotoIn(BaseModel):
    media_id: int | None = None
    """`null` clears the photo."""

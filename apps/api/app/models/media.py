"""Uploaded images (Phase 6). The database holds metadata and opaque storage
keys only; bytes live in the configured storage backend, and clients are only
ever given URLs -- never a filesystem path or storage key."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class MediaFolder(Base, TimestampMixin):
    __tablename__ = "media_folders"
    __table_args__ = (
        # NULL parents (root folders) must also be unique by name.
        Index("uq_media_folders_parent_name", "parent_id", "name", unique=True, postgresql_nulls_not_distinct=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("media_folders.id", ondelete="CASCADE"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Media(Base, TimestampMixin):
    __tablename__ = "media"
    __table_args__ = (Index("ix_media_folder_created", "folder_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    """Unguessable id used in URLs (`/api/v1/media/{public_id}/{variant}`)."""
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("media_folders.id", ondelete="SET NULL"), nullable=True)
    uploader_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    """Display only: sanitized, never used to build a storage key or path."""
    alt_text: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """Size of the *uploaded* file (before optimisation)."""
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    variants: Mapped[list["MediaVariant"]] = relationship(
        back_populates="media", cascade="all, delete-orphan", order_by="MediaVariant.width", lazy="selectin"
    )


class MediaVariant(Base):
    __tablename__ = "media_variants"
    __table_args__ = (UniqueConstraint("media_id", "name", name="uq_media_variants_media_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(16), nullable=False)  # original | large | medium | thumb
    storage_key: Mapped[str] = mapped_column(String(160), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str] = mapped_column(String(40), nullable=False)

    media: Mapped["Media"] = relationship(back_populates="variants")

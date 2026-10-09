"""Object storage for uploaded media (Phase 6).

One tiny interface, three implementations:

* `LocalStorage`  -- a directory. Zero setup; fine for development or a single node.
* `S3Storage`     -- Amazon S3, Cloudflare R2 or MinIO (anything S3-compatible),
                     selected with `MEDIA_STORAGE_BACKEND=s3`.
* `MemoryStorage` -- tests.

Callers only ever deal in *keys* such as ``media/<public_id>/thumb.webp`` that
this module's callers generate from random ids -- never from user input -- and
`LocalStorage` independently refuses any key that could leave its root, so a
bug elsewhere still cannot become a path traversal.
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.core.config import settings

_KEY = re.compile(r"^[a-z0-9][a-z0-9/_.-]{0,159}$")


class StorageError(Exception):
    pass


class StorageNotFound(StorageError):
    pass


def validate_key(key: str) -> str:
    if not _KEY.match(key) or ".." in key or "//" in key or key.endswith("/"):
        raise StorageError("invalid storage key")
    return key


class StorageBackend(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...


class MemoryStorage(StorageBackend):
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[validate_key(key)] = (data, content_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[validate_key(key)][0]
        except KeyError as exc:
            raise StorageNotFound(key) from exc

    async def delete(self, key: str) -> None:
        self.objects.pop(validate_key(key), None)


class LocalStorage(StorageBackend):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if self.root != path and self.root not in path.parents:
            raise StorageError("key escapes the storage root")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic: a reader never sees a half-written image

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise StorageNotFound(key) from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def _remove() -> None:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()  # tidy the per-image directory when empty
            except OSError:
                pass

        await asyncio.to_thread(_remove)


class S3Storage(StorageBackend):
    """boto3 is synchronous, so every call runs in a worker thread."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            # MinIO (and some R2 setups) need path-style addressing.
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        validate_key(key)

        def _put() -> None:
            kwargs = dict(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
                CacheControl="public, max-age=31536000, immutable",
            )
            try:
                self._client.put_object(**kwargs)
            except self._client.exceptions.NoSuchBucket:
                # The store came up after the API did (local MinIO starts empty): create the bucket and retry once.
                self._client.create_bucket(Bucket=self.bucket)
                self._client.put_object(**kwargs)

        await asyncio.to_thread(_put)

    async def get(self, key: str) -> bytes:
        validate_key(key)

        def _get() -> bytes:
            try:
                return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except self._client.exceptions.NoSuchKey as exc:
                raise StorageNotFound(key) from exc

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def ensure_bucket(self) -> None:
        """Create the bucket if it is missing (local MinIO). Real S3/R2 buckets are
        provisioned out of band; a failure here is logged by the caller, not fatal."""

        def _ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self.bucket)
            except Exception:
                self._client.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(_ensure)


@lru_cache
def get_storage() -> StorageBackend:
    if settings.media_storage_backend.lower() == "s3":
        return S3Storage()
    return LocalStorage(settings.media_local_root)

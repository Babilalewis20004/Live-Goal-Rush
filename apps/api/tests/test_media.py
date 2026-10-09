"""Media: upload validation, optimisation, delivery, permissions, folders and
the storage backends (Phase 6)."""

import io

import pytest
from PIL import Image

from app.core.config import settings
from app.models.enums import UserRole
from app.models.player import Player
from app.services.media_service import VARIANT_NAMES, process_image, sanitize_filename
from app.services.storage import LocalStorage, S3Storage, StorageError, StorageNotFound, validate_key

API = "/api/v1"


# -- processing (pure) -------------------------------------------------------------------------


def test_every_variant_is_produced_resized_and_webp(make_image):
    result = process_image(make_image("PNG", (3000, 2000)))
    by_name = {v.name: v for v in result.variants}
    assert set(by_name) == set(VARIANT_NAMES)
    assert (result.width, result.height) == (3000, 2000)
    assert max(by_name["large"].width, by_name["large"].height) == 1600
    assert max(by_name["medium"].width, by_name["medium"].height) == 800
    assert max(by_name["thumb"].width, by_name["thumb"].height) == 320
    assert by_name["thumb"].width / by_name["thumb"].height == pytest.approx(1.5, abs=0.02)  # aspect kept
    for variant in by_name.values():
        assert Image.open(io.BytesIO(variant.data)).format == "WEBP"
    assert len(by_name["thumb"].data) < len(by_name["large"].data)


def test_small_images_are_not_upscaled(make_image):
    result = process_image(make_image("JPEG", (400, 300)))
    assert {v.name: (v.width, v.height) for v in result.variants}["large"] == (400, 300)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "GIF"])
def test_accepted_formats(make_image, fmt):
    assert process_image(make_image(fmt, (120, 90))).variants


def test_transparency_survives(make_image):
    result = process_image(make_image("PNG", (120, 90), mode="RGBA"))
    img = Image.open(io.BytesIO(result.variants[0].data))
    assert img.mode == "RGBA"


def test_metadata_and_appended_payloads_are_stripped(make_image):
    exif = Image.Exif()
    exif[0x010E] = "secret description"
    exif[0x8825] = {1: "N"}  # GPS ifd
    jpeg = make_image("JPEG", (200, 200), exif=exif.tobytes())
    assert b"secret description" in jpeg  # the upload really carries it
    polyglot = jpeg + b"<script>alert(1)</script>"
    for variant in process_image(polyglot).variants:
        assert b"secret description" not in variant.data
        assert b"<script" not in variant.data
        assert len(Image.open(io.BytesIO(variant.data)).getexif()) == 0


def test_exif_rotation_is_applied_before_it_is_dropped(make_image):
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees: a 300x100 upload displays as 100x300
    result = process_image(make_image("JPEG", (300, 100), exif=exif.tobytes()))
    assert (result.width, result.height) == (100, 300)


def test_animated_gif_uses_the_first_frame(make_image):
    first = Image.new("RGB", (100, 100), (255, 0, 0))
    second = Image.new("RGB", (100, 100), (0, 0, 255))
    out = io.BytesIO()
    first.save(out, format="GIF", save_all=True, append_images=[second], duration=100, loop=0)
    result = process_image(out.getvalue())
    assert not getattr(Image.open(io.BytesIO(result.variants[0].data)), "is_animated", False)


@pytest.mark.parametrize(
    "payload,reason",
    [
        (b"", "empty"),
        (b"just some text pretending to be a picture", "not an image"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "svg"),
        (b"<html><script>alert(1)</script></html>", "html"),
        (b"GIF89a" + b"\x00" * 10, "truncated"),
        (b"%PDF-1.4\n%fake", "pdf"),
    ],
)
def test_non_images_are_rejected(payload, reason):
    from app.services.media_service import MediaValidationError

    with pytest.raises(MediaValidationError):
        process_image(payload)


def test_unsupported_image_formats_are_rejected(make_image):
    from app.services.media_service import MediaValidationError

    with pytest.raises(MediaValidationError, match="Only JPEG, PNG, WebP and GIF"):
        process_image(make_image("BMP", (100, 100)))
    with pytest.raises(MediaValidationError, match="Only JPEG, PNG, WebP and GIF"):
        process_image(make_image("TIFF", (100, 100)))


def test_dimension_limits(make_image, monkeypatch):
    from app.services.media_service import MediaTooLargeError, MediaValidationError

    with pytest.raises(MediaValidationError, match="too small"):
        process_image(make_image("PNG", (20, 20)))
    monkeypatch.setattr(settings, "media_max_side", 500)
    with pytest.raises(MediaValidationError, match="too large"):
        process_image(make_image("PNG", (600, 200)))
    monkeypatch.setattr(settings, "media_max_side", 8000)
    monkeypatch.setattr(settings, "media_max_bytes", 100)
    with pytest.raises(MediaTooLargeError):
        process_image(make_image("PNG", (300, 300)))


def test_decompression_bombs_are_refused(make_image, monkeypatch):
    from app.services.media_service import MediaValidationError

    monkeypatch.setattr(settings, "media_max_pixels", 10_000)  # 100x100
    with pytest.raises(MediaValidationError):
        process_image(make_image("PNG", (400, 400)))


def test_filenames_are_sanitised_for_display_only():
    assert sanitize_filename("../../etc/passwd.png") == "passwd.png"
    assert sanitize_filename("C:\\Users\\x\\evil<script>.png") == "evilscript.png"
    assert sanitize_filename(None) == ""
    assert len(sanitize_filename("a" * 500 + ".png")) <= 120


# -- upload API ------------------------------------------------------------------------------------


async def test_upload_requires_a_staff_role(client, make_user, upload):
    assert (await upload({})).status_code == 401
    _, fan = await make_user("fan@example.com")
    assert (await upload(fan)).status_code == 403


async def test_an_author_can_upload_and_gets_urls_but_never_paths(make_user, upload, memory_storage):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    resp = await upload(author, filename="../../Match Day.png", alt_text="Fans at the ground")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "Match Day.png" and body["alt_text"] == "Fans at the ground"
    assert set(body["variants"]) == set(VARIANT_NAMES)
    assert body["url"].endswith("/large") and body["thumb_url"].endswith("/thumb")
    text = resp.text
    for leak in ("media/", ".webp", "storage", "\\\\", "/tmp", "media-data"):
        if leak == "media/":
            continue  # the public URL path legitimately starts /api/v1/media/
        assert leak not in text
    assert len(memory_storage.objects) == len(VARIANT_NAMES)
    assert all(key.endswith(".webp") for key in memory_storage.objects)


async def test_upload_ignores_the_declared_type_and_judges_the_bytes(client, make_user, upload):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    # an HTML payload claiming to be a JPEG
    resp = await upload(author, data=b"<html><script>alert(1)</script></html>", filename="x.jpg", content_type="image/jpeg")
    assert resp.status_code == 422
    # a real PNG with a lying filename and type is accepted for what it is
    from PIL import Image as _I
    import io as _io

    buf = _io.BytesIO()
    _I.new("RGB", (100, 100), (1, 2, 3)).save(buf, format="PNG")
    resp = await upload(author, data=buf.getvalue(), filename="evil.html", content_type="text/html")
    assert resp.status_code == 201
    assert resp.json()["variants"]["large"]["url"].endswith("/large")  # served as webp regardless of the name


async def test_oversized_uploads_are_refused_without_being_stored(make_user, upload, memory_storage, make_image, monkeypatch):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    monkeypatch.setattr(settings, "media_max_bytes", 2000)
    resp = await upload(author, data=make_image("PNG", (800, 800)))
    assert resp.status_code == 413
    assert memory_storage.objects == {}


async def test_invalid_images_leave_nothing_behind(make_user, upload, memory_storage, session_factory):
    from sqlalchemy import select

    from app.models.media import Media

    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    assert (await upload(author, data=b"not an image")).status_code == 422
    assert memory_storage.objects == {}
    async with session_factory() as session:
        assert (await session.execute(select(Media))).first() is None


async def test_a_failed_save_cleans_up_the_stored_objects(make_user, upload, memory_storage, monkeypatch):
    from app.services import media_service

    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    original = media_service.Media

    class Boom(original):  # type: ignore[misc,valid-type]
        def __init__(self, **kw):
            raise RuntimeError("database exploded")

    monkeypatch.setattr(media_service, "Media", Boom)
    with pytest.raises(RuntimeError):
        await upload(author)
    assert memory_storage.objects == {}


async def test_upload_rate_limit(make_user, upload, make_image):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    small = make_image("PNG", (70, 70))
    codes = [(await upload(author, data=small)).status_code for _ in range(settings.media_uploads_per_minute + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {201}


# -- delivery ---------------------------------------------------------------------------------------


async def test_images_are_served_immutable_with_etag_and_safe_headers(client, make_user, upload):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    media = (await upload(author)).json()
    path = media["variants"]["thumb"]["url"].replace(settings.public_api_url, "")
    resp = await client.get(path)  # no auth: images are public
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/webp"
    assert "immutable" in resp.headers["cache-control"] and "max-age=31536000" in resp.headers["cache-control"]
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in resp.headers["content-security-policy"]
    assert Image.open(io.BytesIO(resp.content)).format == "WEBP"
    again = await client.get(path, headers={"If-None-Match": resp.headers["etag"]})
    assert again.status_code == 304 and again.content == b""


async def test_delivery_is_cached_in_redis_metadata(client, make_user, upload, fake_redis):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    media = (await upload(author)).json()
    path = media["variants"]["medium"]["url"].replace(settings.public_api_url, "")
    await client.get(path)
    public_id = path.split("/")[-2]
    assert await fake_redis.get(f"media:meta:{public_id}:medium") is not None


@pytest.mark.parametrize("path", ["/zzzz/thumb", "/" + "a" * 24 + "/thumb", "/" + "a" * 24 + "/../../etc/passwd", "/" + "a" * 24 + "/gigantic"])
async def test_bad_or_unknown_image_paths_are_404(client, path):
    assert (await client.get(f"{API}/media{path}")).status_code == 404


async def test_public_base_url_points_straight_at_the_cdn(make_user, upload, monkeypatch):
    monkeypatch.setattr(settings, "media_public_base_url", "https://cdn.livepitch.example/")
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    body = (await upload(author)).json()
    assert body["url"].startswith("https://cdn.livepitch.example/media/") and body["url"].endswith("/large.webp")


# -- permissions, library, deletion -----------------------------------------------------------------------


async def test_authors_see_only_their_own_uploads_editors_see_all(client, make_user, upload):
    _, alice = await make_user("alice@example.com", UserRole.AUTHOR)
    _, bob = await make_user("bob@example.com", UserRole.AUTHOR)
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    mine = (await upload(alice)).json()
    await upload(bob)
    assert (await client.get(f"{API}/editor/media", headers=alice)).json()["total"] == 1
    assert (await client.get(f"{API}/editor/media", headers=editor)).json()["total"] == 2
    assert (await client.patch(f"{API}/editor/media/{mine['id']}", json={"alt_text": "x"}, headers=bob)).status_code == 403
    assert (await client.delete(f"{API}/editor/media/{mine['id']}", headers=bob)).status_code == 403
    assert (await client.patch(f"{API}/editor/media/{mine['id']}", json={"alt_text": "Edited"}, headers=editor)).json()["alt_text"] == "Edited"


async def test_delete_removes_every_stored_object(client, make_user, upload, memory_storage):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    media = (await upload(author)).json()
    assert len(memory_storage.objects) == 4
    assert (await client.delete(f"{API}/editor/media/{media['id']}", headers=author)).status_code == 204
    assert memory_storage.objects == {}
    assert (await client.get(media["url"].replace(settings.public_api_url, ""))).status_code == 404


async def test_media_in_use_cannot_be_deleted(client, make_user, upload, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    media = (await upload(editor)).json()
    article = await publish_article(editor, "With picture", featured_media_id=media["id"])
    assert article["featured_image_url"] == media["url"]
    assert (await client.delete(f"{API}/editor/media/{media['id']}", headers=editor)).status_code == 409
    await client.patch(f"{API}/editor/articles/{article['id']}", json={"featured_media_id": None}, headers=editor)
    assert (await client.delete(f"{API}/editor/media/{media['id']}", headers=editor)).status_code == 204


async def test_an_author_cannot_attach_someone_elses_upload(client, make_user, upload):
    _, alice = await make_user("alice@example.com", UserRole.AUTHOR)
    _, bob = await make_user("bob@example.com", UserRole.AUTHOR)
    theirs = (await upload(alice)).json()
    r = await client.post(f"{API}/editor/articles", json={"title": "Borrowed image", "featured_media_id": theirs["id"]}, headers=bob)
    assert r.status_code == 403
    r = await client.post(f"{API}/editor/articles", json={"title": "Borrowed gallery", "gallery": [{"media_id": theirs["id"]}]}, headers=bob)
    assert r.status_code == 403


async def test_gallery_is_ordered_captioned_and_public(client, make_user, upload, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    a, b = (await upload(editor)).json(), (await upload(editor)).json()
    article = await publish_article(
        editor, "Photo story", gallery=[{"media_id": b["id"], "caption": "Second shot"}, {"media_id": a["id"], "caption": "First shot"}]
    )
    public = (await client.get(f"{API}/articles/{article['slug']}")).json()
    assert [g["caption"] for g in public["gallery"]] == ["Second shot", "First shot"]
    assert public["gallery"][0]["url"] == b["url"] and public["gallery"][0]["thumb_url"] == b["thumb_url"]
    assert public["gallery"][0]["alt"] == "Second shot"


async def test_editors_can_set_and_clear_a_player_photo(seeded_client, make_user, upload, lookup, session_factory):
    from sqlalchemy import select

    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    media = (await upload(editor)).json()
    haaland = await lookup(Player, "Haaland")
    url = f"{API}/editor/media/players/{haaland}/photo"
    assert (await seeded_client.put(url, json={"media_id": media["id"]}, headers=author)).status_code == 403
    assert (await seeded_client.put(url, json={"media_id": media["id"]}, headers=editor)).status_code == 200
    player = (await seeded_client.get(f"{API}/players/{haaland}")).json()
    assert player["photo_url"] == media["variants"]["medium"]["url"]
    assert (await seeded_client.delete(f"{API}/editor/media/{media['id']}", headers=editor)).status_code == 409  # in use
    assert (await seeded_client.put(url, json={"media_id": None}, headers=editor)).status_code == 200
    async with session_factory() as session:
        assert (await session.execute(select(Player.photo_url).where(Player.id == haaland))).scalar_one() is None


async def test_folders(client, make_user, upload):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    folder = (await client.post(f"{API}/editor/media/folders", json={"name": "Match day"}, headers=author)).json()
    assert (await client.post(f"{API}/editor/media/folders", json={"name": "match day"}, headers=author)).status_code in (201, 422)
    assert (await client.post(f"{API}/editor/media/folders", json={"name": "Match day"}, headers=author)).status_code == 422  # duplicate
    assert (await client.post(f"{API}/editor/media/folders", json={"name": "x", "parent_id": 999}, headers=author)).status_code == 422
    media = (await upload(author, folder_id=str(folder["id"]))).json()
    assert media["folder_id"] == folder["id"]
    listed = (await client.get(f"{API}/editor/media/folders", headers=author)).json()
    assert next(f for f in listed if f["id"] == folder["id"])["media_count"] == 1
    assert (await client.get(f"{API}/editor/media", params={"folder_id": folder["id"]}, headers=author)).json()["total"] == 1
    assert (await client.delete(f"{API}/editor/media/folders/{folder['id']}", headers=editor)).status_code == 409  # not empty
    moved = await client.patch(f"{API}/editor/media/{media['id']}", json={"move_to_root": True}, headers=author)
    assert moved.json()["folder_id"] is None
    assert (await client.delete(f"{API}/editor/media/folders/{folder['id']}", headers=author)).status_code == 403  # editors only
    assert (await client.delete(f"{API}/editor/media/folders/{folder['id']}", headers=editor)).status_code == 204


# -- storage backends ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "media/../x", "media//x", "Media/UPPER.webp", "media/x y.webp", "", "a" * 200, "media/x/"])
def test_storage_keys_are_validated(key):
    with pytest.raises(StorageError):
        validate_key(key)


async def test_local_storage_round_trip_and_containment(tmp_path):
    storage = LocalStorage(tmp_path)
    await storage.put("media/abc/thumb.webp", b"bytes", "image/webp")
    assert (tmp_path / "media" / "abc" / "thumb.webp").read_bytes() == b"bytes"
    assert await storage.get("media/abc/thumb.webp") == b"bytes"
    await storage.delete("media/abc/thumb.webp")
    with pytest.raises(StorageNotFound):
        await storage.get("media/abc/thumb.webp")
    assert not (tmp_path / "media" / "abc").exists()  # tidied
    for bad in ("../outside.webp", "media/../../outside.webp"):
        with pytest.raises(StorageError):
            await storage.put(bad, b"x", "image/webp")
    assert not list(tmp_path.parent.glob("outside.webp"))


async def test_s3_storage_uses_the_expected_calls(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeBody:
        def read(self):
            return b"payload"

    class NoSuchKey(Exception):
        pass

    from types import SimpleNamespace

    class FakeClient:
        exceptions = SimpleNamespace(NoSuchKey=NoSuchKey)

        def put_object(self, **kw):
            calls.append(("put", kw))

        def get_object(self, **kw):
            calls.append(("get", kw))
            if kw["Key"].endswith("missing.webp"):
                raise NoSuchKey()
            return {"Body": FakeBody()}

        def delete_object(self, **kw):
            calls.append(("delete", kw))

    import boto3

    captured = {}

    def fake_client(service, **kw):
        captured.update(kw)
        return FakeClient()

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setattr(settings, "s3_endpoint_url", "http://minio:9000")
    monkeypatch.setattr(settings, "s3_bucket", "bucket")
    storage = S3Storage()
    assert captured["endpoint_url"] == "http://minio:9000"
    await storage.put("media/a/large.webp", b"x", "image/webp")
    assert await storage.get("media/a/large.webp") == b"payload"
    with pytest.raises(StorageNotFound):
        await storage.get("media/a/missing.webp")
    await storage.delete("media/a/large.webp")
    put = dict(calls)["put"]
    assert put["Bucket"] == "bucket" and put["ContentType"] == "image/webp" and "immutable" in put["CacheControl"]
    with pytest.raises(StorageError):
        await storage.put("../escape", b"x", "image/webp")


async def test_s3_creates_a_missing_bucket_on_first_upload_and_retries_once(monkeypatch):
    """Local MinIO may come up after the API: the first put creates the bucket instead of failing."""
    from types import SimpleNamespace

    import boto3

    class NoSuchBucket(Exception):
        pass

    events = []

    class FakeClient:
        exceptions = SimpleNamespace(NoSuchBucket=NoSuchBucket, NoSuchKey=KeyError)
        created = False

        def put_object(self, **kw):
            if not FakeClient.created:
                events.append("put-failed")
                raise NoSuchBucket()
            events.append("put-ok")

        def create_bucket(self, **kw):
            FakeClient.created = True
            events.append("create")

    monkeypatch.setattr(boto3, "client", lambda *a, **kw: FakeClient())
    storage = S3Storage()
    await storage.put("media/a/large.webp", b"x", "image/webp")
    assert events == ["put-failed", "create", "put-ok"]

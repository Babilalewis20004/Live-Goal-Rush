import re
import unicodedata

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, max_length: int = 120) -> str:
    """URL-safe slug: accents folded, lower-case, runs of anything else
    collapsed to one hyphen. May be empty (e.g. an all-symbol title) -- callers
    decide the fallback."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", folded.lower()).strip("-")
    return slug[:max_length].strip("-")

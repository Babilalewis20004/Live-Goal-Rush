"""Allow-list HTML sanitizer for article bodies (discovery §45).

Editor-supplied HTML is never trusted: it is parsed and *rebuilt* from an
allow-list, so what comes out contains only the tags, attributes and URL
schemes named below, with every text node and attribute value escaped.
Anything not allowed is dropped (its text is kept, except for tags whose
*content* is itself dangerous -- script, style, iframe, ... -- which are
removed entirely).

Standard library only: `html.parser` tolerates broken markup and decodes
entities before we see them, so tricks like `jav&#x61;script:` are decoded and
then rejected by the URL check rather than slipping through a regex.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

ALLOWED_TAGS = frozenset(
    {"p", "br", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "ul", "ol", "li", "blockquote", "a", "img", "hr"}
)
VOID_TAGS = frozenset({"br", "img", "hr"})
# Tags whose *contents* must not survive either (text inside <script> is code).
DROP_CONTENT_TAGS = frozenset(
    {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "form", "textarea", "title", "head", "select", "option", "button"}
)
ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "title"}),
}
_LINK_SCHEMES = frozenset({"http", "https", "mailto"})
_IMAGE_SCHEMES = frozenset({"http", "https"})
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_STRIP_RE = re.compile(r"[\x00-\x20\x7f-\x9f\u200b-\u200f\u2028\u2029\ufeff]")


def host_allowed(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    """True when no allow-list is configured, or the URL's host is (a subdomain of)
    one of the allowed hosts."""
    if not allowed_hosts:
        return True
    host = (urlparse(_STRIP_RE.sub("", url)).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in allowed_hosts)


def is_safe_url(value: str, *, schemes: frozenset[str] = _LINK_SCHEMES, allow_relative: bool = True) -> bool:
    """True for an absolute URL with an allowed scheme, or (optionally) a
    same-site path/fragment. Whitespace and control characters are removed
    *before* looking at the scheme, because browsers ignore them inside it
    (`java\\tscript:`)."""
    cleaned = _STRIP_RE.sub("", value)
    if not cleaned:
        return False
    match = _SCHEME_RE.match(cleaned)
    if match:
        return match.group(1).lower() in schemes
    if cleaned.startswith("//"):  # protocol-relative -> arbitrary host, no scheme to vet
        return False
    if not allow_relative:
        return False
    return cleaned.startswith(("/", "#"))


class _Sanitizer(HTMLParser):
    def __init__(self, image_hosts: tuple[str, ...] = ()) -> None:
        super().__init__(convert_charrefs=True)
        self._image_hosts = image_hosts
        self.out: list[str] = []
        self._open: list[str] = []
        self._drop_depth = 0

    # -- tags ---------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._drop_depth:
            if tag in DROP_CONTENT_TAGS and tag not in VOID_TAGS:
                self._drop_depth += 1
            return
        if tag in DROP_CONTENT_TAGS:
            self._drop_depth = 1
            return
        if tag not in ALLOWED_TAGS:
            return

        rendered: list[str] = []
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        for name in ALLOWED_ATTRS.get(tag, frozenset()):
            if name not in attr_map:
                continue
            value = attr_map[name]
            if name == "href" and not is_safe_url(value):
                continue
            if name == "src" and not (
                is_safe_url(value, schemes=_IMAGE_SCHEMES, allow_relative=False)
                and host_allowed(value, self._image_hosts)
            ):
                continue
            rendered.append(f'{name}="{html.escape(value, quote=True)}"')

        if tag == "img" and not any(a.startswith("src=") for a in rendered):
            return  # an image without a usable source is just noise
        if tag == "a":
            rendered.append('rel="noopener noreferrer nofollow"')
        if tag == "img":
            rendered.append('loading="lazy"')
            if not any(a.startswith("alt=") for a in rendered):
                rendered.append('alt=""')

        self.out.append(f"<{tag}{' ' + ' '.join(rendered) if rendered else ''}>")
        if tag not in VOID_TAGS:
            self._open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `<br/>`, `<img ... />`; a self-closed non-void tag (`<script/>`) is
        # treated as an opening tag, exactly as HTML parsers do.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self._drop_depth:
            if tag in DROP_CONTENT_TAGS:
                self._drop_depth -= 1
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self._open:
            return
        # Close anything left open inside it so the output stays well-nested.
        while self._open:
            top = self._open.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    # -- text ---------------------------------------------------------------
    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:  # comments (incl. IE conditionals) are dropped
        return

    def handle_decl(self, decl: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    def finish(self) -> str:
        self.close()
        while self._open:
            self.out.append(f"</{self._open.pop()}>")
        return "".join(self.out).strip()


def sanitize_html(raw: str, *, image_hosts: tuple[str, ...] = ()) -> str:
    """`image_hosts`: if given, `<img>` sources must come from these hosts (or
    their subdomains); images from anywhere else are dropped."""
    parser = _Sanitizer(image_hosts)
    parser.feed(raw)
    return parser.finish()


_BLOCK_END = re.compile(r"</(?:p|h[2-4]|li|blockquote|ul|ol)>|<hr>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(sanitized: str) -> str:
    """Plain-text paragraphs (blank-line separated) from *already sanitized*
    HTML, for clients without an HTML renderer (React Native)."""
    text = _BR.sub("\n", sanitized)
    text = _BLOCK_END.sub("\n\n", text)
    text = html.unescape(_TAG.sub("", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_BLOCK_TYPES = {"h2": "heading", "h3": "heading", "h4": "heading", "p": "paragraph", "li": "list_item", "blockquote": "quote"}


class _Blocks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, str]] = []
        self._kind: str | None = None
        self._buf: list[str] = []

    def _flush(self) -> None:
        text = re.sub(r"[ \t]+", " ", "".join(self._buf)).strip()
        if text:
            self.blocks.append({"type": self._kind or "paragraph", "text": text})
        self._buf = []
        self._kind = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TYPES:
            self._flush()
            self._kind = _BLOCK_TYPES[tag]
        elif tag == "br":
            self._buf.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TYPES:
            self._flush()

    def handle_data(self, data: str) -> None:
        self._buf.append(data)


def html_to_blocks(sanitized: str) -> list[dict[str, str]]:
    """Structured blocks (`heading` / `paragraph` / `list_item` / `quote`) from
    *already sanitized* HTML, for clients that render natively rather than
    through a browser (React Native). Inline markup is flattened to text."""
    parser = _Blocks()
    parser.feed(sanitized)
    parser.close()
    parser._flush()
    return parser.blocks

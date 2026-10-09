"""The article body sanitizer is the XSS boundary for editor-supplied HTML
(discovery §45), so it is tested against the classic bypasses, not just the
happy path."""

import pytest

from app.services.html_sanitizer import html_to_blocks, html_to_text, is_safe_url, sanitize_html


def test_keeps_basic_formatting():
    html = "<h2>Title</h2><p>Hello <strong>world</strong> and <em>you</em>.</p><ul><li>One</li><li>Two</li></ul>"
    assert sanitize_html(html) == html


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<SCRIPT SRC=//evil.example/x.js></SCRIPT>",
        "<style>body{background:url(javascript:alert(1))}</style>",
        "<iframe src='https://evil.example'></iframe>",
        "<object data='x'></object><embed src='x'>",
        "<svg onload=alert(1)><circle/></svg>",
        "<math><mi xlink:href='javascript:alert(1)'>x</mi></math>",
        "<form action='https://evil.example'><input name=x></form>",
    ],
)
def test_dangerous_elements_and_their_contents_are_removed(payload):
    out = sanitize_html(f"<p>safe</p>{payload}")
    lowered = out.lower()
    assert "alert" not in lowered
    assert "<script" not in lowered and "<iframe" not in lowered and "<svg" not in lowered
    assert "evil.example" not in lowered
    assert "<p>safe</p>" in out


def test_split_tag_trick_leaves_only_inert_escaped_text():
    out = sanitize_html("<p>safe</p><scr<script>ipt>alert(1)</scr</script>ipt>")
    # whatever text is left is escaped data, never markup
    assert out.replace("<p>", "").replace("</p>", "").count("<") == 0
    assert "<script" not in out.lower()


def test_event_handler_and_style_attributes_are_dropped():
    out = sanitize_html('<p onclick="alert(1)" style="color:red" class="x" id="y">hi</p>')
    assert out == "<p>hi</p>"
    out = sanitize_html('<img src="https://cdn.example/a.jpg" onerror="alert(1)" alt="a">')
    assert "onerror" not in out and 'src="https://cdn.example/a.jpg"' in out


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "java\tscript:alert(1)",
        "java&#x09;script:alert(1)",
        "&#106;avascript:alert(1)",
        " javascript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "//evil.example/phish",
    ],
)
def test_dangerous_link_targets_are_removed(href):
    out = sanitize_html(f'<a href="{href}">click</a>')
    assert "href" not in out
    assert "click" in out


def test_safe_links_survive_with_hardened_rel():
    out = sanitize_html('<a href="https://example.com/a?b=1&c=2" title="T">x</a>')
    assert 'href="https://example.com/a?b=1&amp;c=2"' in out
    assert 'rel="noopener noreferrer nofollow"' in out
    assert 'href="/team/4"' in sanitize_html('<a href="/team/4">t</a>')
    assert 'href="mailto:desk@example.com"' in sanitize_html('<a href="mailto:desk@example.com">m</a>')


def test_images_need_an_http_source_and_get_alt_and_lazy_loading():
    assert "<img" not in sanitize_html('<img src="javascript:alert(1)">')
    assert "<img" not in sanitize_html('<img src="data:image/svg+xml;base64,AAAA">')
    assert "<img" not in sanitize_html('<img src="/local.png">')  # only absolute http(s)
    out = sanitize_html('<img src="https://cdn.example/a.png">')
    assert 'alt=""' in out and 'loading="lazy"' in out


def test_text_is_escaped_not_interpreted():
    out = sanitize_html("<p>1 < 2 & 3 > 2 &lt;script&gt;alert(1)&lt;/script&gt;</p>")
    assert "<script" not in out
    assert "&lt;script&gt;" in out


def test_comments_and_conditional_blocks_are_dropped():
    out = sanitize_html("<p>a</p><!-- <script>alert(1)</script> --><!--[if IE]><script>x</script><![endif]--><p>b</p>")
    assert out == "<p>a</p><p>b</p>"


def test_broken_markup_is_repaired_into_balanced_html():
    assert sanitize_html("<p>one <strong>two") == "<p>one <strong>two</strong></p>"
    assert sanitize_html("</p></div>text") == "text"
    assert sanitize_html("<p><em>x</p></em>") == "<p><em>x</em></p>"


def test_unknown_tags_are_unwrapped_keeping_text():
    assert sanitize_html("<div><span>keep me</span></div>") == "keep me"


def test_is_safe_url():
    assert is_safe_url("https://a.example")
    assert is_safe_url("/relative")
    assert is_safe_url("#frag")
    assert not is_safe_url("")
    assert not is_safe_url("javascript:1")
    assert not is_safe_url("//host")
    assert not is_safe_url("/x", allow_relative=False)
    assert not is_safe_url("mailto:a@b.c", schemes=frozenset({"http", "https"}))


def test_html_to_text_gives_blank_line_separated_paragraphs():
    text = html_to_text("<h2>Head</h2><p>One &amp; two</p><p>Line<br>break</p><ul><li>a</li><li>b</li></ul>")
    assert text == "Head\n\nOne & two\n\nLine\nbreak\n\na\n\nb"


def test_html_to_blocks_gives_typed_blocks_for_native_clients():
    blocks = html_to_blocks(
        "<h2>Head</h2><p>One <strong>bold</strong> &amp; two</p><p>Line<br>break</p>"
        "<ul><li>a</li><li>b</li></ul><blockquote>Quoted</blockquote>stray text"
    )
    assert blocks == [
        {"type": "heading", "text": "Head"},
        {"type": "paragraph", "text": "One bold & two"},
        {"type": "paragraph", "text": "Line\nbreak"},
        {"type": "list_item", "text": "a"},
        {"type": "list_item", "text": "b"},
        {"type": "quote", "text": "Quoted"},
        {"type": "paragraph", "text": "stray text"},
    ]
    assert html_to_blocks("") == []


def test_body_images_honour_the_host_allow_list():
    html = '<img src="https://cdn.livepitch.example/a.jpg"><img src="https://evil.example/t.gif"><img src="https://livepitch.example/b.jpg">'
    out = sanitize_html(html, image_hosts=("livepitch.example",))
    assert "cdn.livepitch.example/a.jpg" in out and "https://livepitch.example/b.jpg" in out  # host and subdomain
    assert "evil.example" not in out
    assert "evil.example" in sanitize_html(html)  # no allow-list configured: any http(s) host
    assert "evil.example" not in sanitize_html('<img src="https://livepitch.example.evil.example/x.gif">', image_hosts=("livepitch.example",))

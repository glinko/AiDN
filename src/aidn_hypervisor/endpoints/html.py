"""Bounded server-side HTML sanitizer for Marketplace Endpoint descriptions."""

import hashlib
import html
from html.parser import HTMLParser
from urllib.parse import urlsplit

SANITIZER_VERSION = "aidn-marketplace-html.v1"
MAX_SOURCE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 128 * 1024
MAX_NODES = 2_000
MAX_DEPTH = 16

_ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "code",
    "pre",
    "blockquote",
    "hr",
    "br",
    "a",
}
_VOID_TAGS = {"hr", "br"}
_BLOCKED_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "form",
    "template",
    "textarea",
    "title",
    "head",
    "meta",
    "link",
}


def sanitize_marketplace_html(source_html: str) -> tuple[str, str, str]:
    if not isinstance(source_html, str):
        raise ValueError("Marketplace description must be text")
    if len(source_html.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Marketplace description exceeds the source size limit")
    parser = _MarketplaceHTMLParser()
    parser.feed(source_html)
    parser.close()
    sanitized = parser.finish()
    if len(sanitized.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("Marketplace description exceeds the rendered size limit")
    content_hash = "sha256:" + hashlib.sha256(
        f"{SANITIZER_VERSION}\0{sanitized}".encode()
    ).hexdigest()
    return sanitized, SANITIZER_VERSION, content_hash


class _MarketplaceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.blocked_tags: list[str] = []
        self.nodes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count_node()
        tag = tag.lower()
        if self.blocked_tags:
            if tag in _BLOCKED_TAGS:
                self.blocked_tags.append(tag)
            return
        if tag in _BLOCKED_TAGS:
            self.blocked_tags.append(tag)
            return
        if tag not in _ALLOWED_TAGS:
            return
        if len(self.open_tags) >= MAX_DEPTH:
            raise ValueError("Marketplace description nesting exceeds the depth limit")
        attributes = self._safe_attributes(tag, attrs)
        self.output.append("<" + tag + attributes + ">")
        if tag not in _VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.blocked_tags:
            if tag == self.blocked_tags[-1]:
                self.blocked_tags.pop()
            return
        if tag not in self.open_tags:
            return
        while self.open_tags:
            current = self.open_tags.pop()
            self.output.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        self._count_node()
        if not self.blocked_tags:
            self.output.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self._count_node()
        if not self.blocked_tags:
            self.output.append(html.escape(html.unescape(f"&{name};"), quote=False))

    def handle_charref(self, name: str) -> None:
        self._count_node()
        if not self.blocked_tags:
            self.output.append(html.escape(html.unescape(f"&#{name};"), quote=False))

    def handle_comment(self, data: str) -> None:
        self._count_node()

    def finish(self) -> str:
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")
        return "".join(self.output)

    def _count_node(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError("Marketplace description exceeds the node limit")

    @staticmethod
    def _safe_attributes(tag: str, attrs: list[tuple[str, str | None]]) -> str:
        if tag != "a":
            return ""
        href = next((value for name, value in attrs if name.lower() == "href"), None)
        if href is None or not _safe_href(href):
            return ' rel="nofollow noopener noreferrer"'
        return (
            f' href="{html.escape(href, quote=True)}"'
            ' rel="nofollow noopener noreferrer"'
        )


def _safe_href(value: str) -> bool:
    normalized = html.unescape(value).strip()
    if not normalized or any(ord(character) < 0x20 for character in normalized):
        return False
    if normalized.startswith("//"):
        return False
    parsed = urlsplit(normalized)
    if parsed.scheme:
        if parsed.scheme.lower() not in {"https", "mailto"}:
            return False
        if parsed.scheme.lower() == "https" and not parsed.netloc:
            return False
        return True
    return normalized.startswith("#") or normalized.startswith("/")

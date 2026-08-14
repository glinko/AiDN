import pytest
from pydantic import ValidationError

from aidn_hypervisor.endpoints.html import sanitize_marketplace_html
from aidn_hypervisor.endpoints.models import EndpointMarketplaceDescription


def test_marketplace_html_strips_scripts_handlers_styles_and_unsafe_urls() -> None:
    description = EndpointMarketplaceDescription(
        html=(
            '<h2>Speech</h2><script>alert(1)</script>'
            '<p onclick="alert(2)" style="color:red">Fast <strong>ASR</strong></p>'
            '<a href="javascript:alert(3)" target="_blank">Try it</a>'
            '<a href="https://example.com/docs">Docs</a>'
        )
    )

    assert description.html == (
        "<h2>Speech</h2><p>Fast <strong>ASR</strong></p>"
        '<a rel="nofollow noopener noreferrer">Try it</a>'
        '<a href="https://example.com/docs" rel="nofollow noopener noreferrer">Docs</a>'
    )
    assert "script" not in description.html
    assert description.content_hash is not None
    assert description.sanitizer_version == "aidn-marketplace-html.v1"


def test_marketplace_html_preserves_text_but_not_markup_from_unknown_tags() -> None:
    sanitized, _, _ = sanitize_marketplace_html(
        "<custom>hello &amp; <img src=x onerror=alert(1)>world</custom>"
    )

    assert sanitized == "hello &amp; world"


def test_marketplace_html_rejects_tampered_hash_and_empty_result() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        EndpointMarketplaceDescription(
            html="<p>Safe</p>",
            content_hash="sha256:tampered",
        )
    with pytest.raises(ValidationError, match="empty"):
        EndpointMarketplaceDescription(html="<script>alert(1)</script>")


@pytest.mark.parametrize(
    "source",
    [
        "<svg onload=alert(1)><p>hidden</p></svg><p>safe</p>",
        "<p>safe</div><script>alert(1)",
        '<a href="java&#x73;cript:alert(1)">bad</a>',
        '<p style="background:url(javascript:alert(1))">safe</p>',
        '<a href="data:text/html,<script>alert(1)</script>">bad</a>',
    ],
)
def test_marketplace_html_xss_regressions_fail_closed(source: str) -> None:
    sanitized, _, _ = sanitize_marketplace_html(source)

    assert "<script" not in sanitized.lower()
    assert "<svg" not in sanitized.lower()
    assert "javascript:" not in sanitized.lower()
    assert "data:" not in sanitized.lower()
    assert "style=" not in sanitized.lower()


def test_marketplace_html_rejects_oversized_source_and_excessive_nesting() -> None:
    with pytest.raises(ValueError, match="source size"):
        sanitize_marketplace_html("x" * (64 * 1024 + 1))

    nested = "<p>" * 17 + "text" + "</p>" * 17
    with pytest.raises(ValueError, match="depth"):
        sanitize_marketplace_html(nested)

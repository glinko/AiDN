from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.endpoints.api import build_endpoint_router
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_endpoint_router(EndpointService(EndpointStore())))
    return TestClient(app)


def test_marketplace_description_preview_returns_sanitized_html_and_hash() -> None:
    response = _client().post(
        "/api/v1/endpoints/marketplace-description/preview",
        json={"html": '<p>Safe<script>alert(1)</script></p>'},
    )

    assert response.status_code == 200
    description = response.json()["data"]["description"]
    assert description["html"] == "<p>Safe</p>"
    assert description["content_hash"].startswith("sha256:")
    assert response.json()["data"]["rendered_html"] == "<p>Safe</p>"


def test_marketplace_description_preview_rejects_invalid_description() -> None:
    response = _client().post(
        "/api/v1/endpoints/marketplace-description/preview",
        json={"html": "<script>alert(1)</script>"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "marketplace_description_invalid"

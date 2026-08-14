from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.contribution_api import build_contribution_router
from aidn_hypervisor.contributions.service import ContributionAccountingService
from aidn_hypervisor.main import build_app


def test_contribution_api_is_explicitly_non_emitting():
    app = FastAPI()
    app.include_router(build_contribution_router(ContributionAccountingService()))
    client = TestClient(app)

    response = client.get("/api/v1/contributions/status")
    assert response.status_code == 200
    assert response.json() == {
        "mode": "EVIDENCE_ONLY",
        "emits_q": False,
        "ledger_writes": False,
        "protocol": "RFC-0068",
        "reward_preview": True,
        "reward_execution": "ECO-0007_CONSENSUS_GATED",
    }


def test_contribution_api_persists_repository_profile_and_identity():
    app = FastAPI()
    app.include_router(build_contribution_router(ContributionAccountingService()))
    client = TestClient(app)

    profile = client.post(
        "/api/v1/contributions/profiles",
        json={"profile_id": "profile-1", "repository_id": "repo-1"},
    )
    assert profile.status_code == 200
    assert profile.json()["profile_hash"].startswith("sha256:")

    repository = client.post(
        "/api/v1/contributions/repositories",
        json={
            "repository_id": "repo-1",
            "repository_name": "AiDN",
            "canonical_url": "https://github.com/glinko/AiDN",
            "organization_id": "glinko",
            "contribution_profile_id": "profile-1",
            "repository_hash": "sha256:repo",
            "authorization_signature": "ed25519:authority",
        },
    )
    assert repository.status_code == 200

    contributor = client.post(
        "/api/v1/contributions/contributors",
        json={
            "contributor_id": "contributor-1",
            "source_platform_accounts": [{"platform": "github", "account_id": "alice", "handle": "alice"}],
            "valid_from": "2026-08-01T00:00:00+00:00",
            "identity_hash": "sha256:identity",
            "contributor_signature": "ed25519:identity",
        },
    )
    assert contributor.status_code == 200
    assert client.get("/api/v1/contributions/repositories").json()[0]["repository_id"] == "repo-1"
    assert client.get("/api/v1/contributions/contributors").json()[0]["contributor_id"] == "contributor-1"


def test_contribution_api_returns_stable_not_found_code():
    app = FastAPI()
    app.include_router(build_contribution_router(ContributionAccountingService()))
    response = TestClient(app).get("/api/v1/contributions/attestations/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONTRIBUTION_NOT_FOUND"


def test_intake_route_precedes_parameterized_attestation_route():
    router = build_contribution_router(ContributionAccountingService())
    routes = [route.path for route in router.routes]
    assert routes.index("/api/v1/contributions/attestations/intake") < routes.index(
        "/api/v1/contributions/attestations/{contribution_id}"
    )


def test_main_application_wires_contribution_router():
    response = TestClient(build_app()).get("/api/v1/contributions/status")
    assert response.status_code == 200
    assert response.json()["mode"] == "EVIDENCE_ONLY"

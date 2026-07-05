from aidn_hypervisor.operator_onboarding import build_onboarding_payload


def test_build_onboarding_payload_requires_wallet_first() -> None:
    payload = build_onboarding_payload(
        wallet_ready=False,
        provider_count=1,
        bundle_count=1,
        endpoint_items=[],
        first_endpoint_candidate={"bundle_id": "whisper-a"},
        persisted={"completed": False},
    )

    assert payload["current_step"] == "configure_wallet"
    assert payload["workspace"] == "home"
    assert payload["recommended_action"]["action"] == "create-wallet"


def test_build_onboarding_payload_completes_after_first_published_endpoint() -> None:
    payload = build_onboarding_payload(
        wallet_ready=True,
        provider_count=1,
        bundle_count=1,
        endpoint_items=[
            {
                "endpoint_id": "endpoint-1",
                "publication_status": "published",
                "bundle_id": "whisper-a",
            }
        ],
        first_endpoint_candidate={"bundle_id": "whisper-a"},
        persisted={
            "completed": True,
            "completed_via": "first_local_endpoint_published",
        },
    )

    assert payload["completed"] is True
    assert payload["current_step"] == "operate"
    assert payload["recommended_action"]["action"] == "open-home"

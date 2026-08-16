from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.endpoints.models import EndpointManifest
from aidn_hypervisor.inference_gateway import build_inference_router
from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.secrets import FileSecretManager


class _EndpointService:
    def __init__(self, endpoint: EndpointManifest) -> None:
        self.endpoint = endpoint

    def get_endpoint(self, endpoint_id: str):
        if endpoint_id != self.endpoint.endpoint_id:
            raise KeyError(endpoint_id)
        return SimpleNamespace(endpoint=self.endpoint)


class _SessionService:
    def __init__(self) -> None:
        self.opened: list[dict] = []
        self.session = SimpleNamespace(
            session_id="sess-agent-test",
            status="active",
            client_wallet="wallet-test",
        )

    def open_session(self, **payload):
        self.opened.append(payload)
        return SimpleNamespace(session=self.session)

    def require_active_session(self, *, endpoint_id: str, session_id: str):
        if session_id != self.session.session_id:
            raise KeyError(session_id)
        return self.session

    def require_request_budget(self, *, endpoint_id: str, session_id: str):
        return self.session


class _HypervisorService:
    node_id = "node-test"

    def __init__(self) -> None:
        self.submitted = []
        self._result = None

    def submit(self, request):
        self.submitted.append(request)
        task = SimpleNamespace(task_id="task-agent-test", status="completed")
        self._result = {"ok": True, "output_text": "hello from llama", "model_id": "qwen"}
        return task

    def task_result(self, task_id: str):
        return self._result


def _store(tmp_path):
    return McpCredentialStore(
        secret_manager=FileSecretManager(
            path=tmp_path / "secrets.json",
            master_key=os.urandom(32),
        )
    )


def _client(tmp_path, *, local_agent_use: bool = True):
    endpoint = EndpointManifest(
        endpoint_id="ep-local",
        owner_wallet="wallet-test",
        created_at="2026-08-16T00:00:00Z",
        bundle_id="qwen-bundle",
        bundle_hash="sha256:bundle",
        runtime_binding_id="rtb-local",
        configuration_hash="sha256:config",
        display_name="Qwen local",
        model_class="llm_text",
        local_agent_use=local_agent_use,
    )
    store = _store(tmp_path)
    issued = store.create_inference_credential(
        label="personal-agent",
        endpoint_id=endpoint.endpoint_id,
        owner_wallet=endpoint.owner_wallet,
        model_alias="qwen-local",
    )
    service = _HypervisorService()
    sessions = _SessionService()
    app = FastAPI()
    app.include_router(
        build_inference_router(
            hypervisor_service=service,
            endpoint_service=_EndpointService(endpoint),
            session_service=sessions,
            credential_store=store,
        )
    )
    return TestClient(app), issued, service, sessions


def test_models_is_limited_to_the_credential_endpoint(tmp_path) -> None:
    client, issued, _, _ = _client(tmp_path)

    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {issued.token}"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "qwen-local"
    assert response.json()["data"][0]["aidn_endpoint_id"] == "ep-local"


def test_models_reject_endpoint_without_local_agent_opt_in(tmp_path) -> None:
    client, issued, _, _ = _client(tmp_path, local_agent_use=False)

    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {issued.token}"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "endpoint_unavailable"


def test_chat_completion_opens_owner_session_and_preserves_editable_parameters(tmp_path) -> None:
    client, issued, service, sessions = _client(tmp_path)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {issued.token}"},
        json={
            "model": "qwen-local",
            "messages": [{"role": "user", "content": "Say hello"}],
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 128,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello from llama"
    assert len(sessions.opened) == 1
    request = service.submitted[0]
    assert request.constraints["endpoint_id"] == "ep-local"
    assert request.constraints["session_id"] == "sess-agent-test"
    assert request.payload["messages"][0]["content"] == "Say hello"
    assert request.payload["temperature"] == 0.2
    assert request.payload["top_p"] == 0.8
    assert request.payload["max_tokens"] == 128


def test_streaming_is_rejected_explicitly_in_mvp(tmp_path) -> None:
    client, issued, _, _ = _client(tmp_path)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {issued.token}"},
        json={
            "model": "qwen-local",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "streaming_not_supported"


def test_invalid_bearer_token_cannot_reach_task_lifecycle(tmp_path) -> None:
    client, _, service, _ = _client(tmp_path)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={
            "model": "qwen-local",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert service.submitted == []


def test_chat_completion_rejects_endpoint_without_local_agent_opt_in(tmp_path) -> None:
    client, issued, service, _ = _client(tmp_path, local_agent_use=False)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {issued.token}"},
        json={
            "model": "qwen-local",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "endpoint_unavailable"
    assert "Local Agent Use" in response.json()["error"]["message"]
    assert service.submitted == []

"""Direct RFC-0054 execution for an Endpoint-approved Runtime Binding."""

from datetime import UTC, datetime, timedelta
from math import isfinite
from uuid import uuid4

from aidn_hypervisor.accounting.llamacpp import build_llamacpp_usage_profile
from aidn_hypervisor.accounting.models import AccountingContract
from aidn_hypervisor.accounting.ollama import build_ollama_usage_profile
from aidn_hypervisor.accounting.proxy import build_proxy_opaque_usage_profile
from aidn_hypervisor.accounting.tts import build_tts_usage_profile
from aidn_hypervisor.accounting.vllm import build_vllm_usage_profile
from aidn_hypervisor.accounting.whisper import build_whisper_usage_profile
from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.adapters.ollama import OllamaGenerateAdapter
from aidn_hypervisor.runtime_protocol.adapters.tts import OpenAITtsAdapter
from aidn_hypervisor.runtime_protocol.adapters.proxy import ProxyOpenAIAdapter
from aidn_hypervisor.runtime_protocol.adapters.vllm import VllmOpenAIAdapter
from aidn_hypervisor.runtime_protocol.adapters.whisper import WhisperHttpAdapter
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeExecuteRequest,
    RuntimeHello,
    RuntimeHelloComplete,
    canonical_hash,
)
from aidn_hypervisor.runtime_protocol.service import RuntimeProtocolService


class ApprovedRuntimeDispatchError(ValueError):
    """The approved Endpoint binding cannot safely execute this Request."""


_DEFAULT_RUNTIME_TIMEOUT_SECONDS = 90.0
_MIN_REQUEST_DEADLINE_SECONDS = 120.0
_REQUEST_DEADLINE_GRACE_SECONDS = 5.0


def _runtime_timeout_seconds(endpoint) -> float:
    """Resolve the operator-approved request timeout for one Endpoint.

    The adapter timeout is part of the immutable Endpoint runtime contract.
    Falling back to the historical 90-second value keeps legacy Endpoints
    safe while allowing long-running local models to use their configured
    budget instead of being cancelled by an unrelated adapter default.
    """

    runtime = getattr(endpoint, "runtime", None)
    configured = getattr(runtime, "timeout", None)
    if configured is None:
        return _DEFAULT_RUNTIME_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(configured)
    except (TypeError, ValueError) as error:
        raise ApprovedRuntimeDispatchError(
            "Endpoint runtime timeout must be a positive number"
        ) from error
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ApprovedRuntimeDispatchError(
            "Endpoint runtime timeout must be a positive number"
        )
    return timeout_seconds


class ApprovedRuntimeDispatcher:
    """Resolve an Endpoint Binding, handshake it, and dispatch one Request.

    Each supported Provider adapter is selected explicitly. Unknown adapters
    must not fall back to the legacy task-plugin invocation path.
    """

    def __init__(
        self,
        *,
        provider_inventory,
        runtime_protocol_store,
        hypervisor_id: str,
        network_revision: str = "mvp-0001",
    ) -> None:
        self.provider_inventory = provider_inventory
        self.runtime_protocol_store = runtime_protocol_store
        self.hypervisor_id = hypervisor_id
        self.network_revision = network_revision

    def execute(
        self,
        *,
        endpoint,
        session,
        request_id: str,
        request_payload: dict,
        request_deadline: str | None = None,
        streaming: bool = False,
    ):
        binding_id = endpoint.runtime_binding_id
        if not binding_id:
            raise ApprovedRuntimeDispatchError(
                "Endpoint has no approved Runtime Binding"
            )
        binding = self.provider_inventory.store.get_runtime_binding(binding_id)
        if binding.status != "ready" or binding.operational_state != "READY":
            raise ApprovedRuntimeDispatchError("Runtime Binding is not ready")
        if binding.adapter_id not in {
            "llamacpp-openai",
            "ollama-generate",
            "openai-tts",
            "proxy-openai",
            "vllm-openai",
            "whisper-http",
        }:
            raise ApprovedRuntimeDispatchError(
                f"Unsupported approved Runtime Adapter: {binding.adapter_id}"
            )
        if session.endpoint_id != endpoint.endpoint_id:
            raise ApprovedRuntimeDispatchError("Session Endpoint does not match Runtime Endpoint")
        if session.endpoint_configuration_hash != endpoint.configuration_hash:
            raise ApprovedRuntimeDispatchError(
                "Session Endpoint Configuration is no longer current"
            )
        if (
            not session.session_contract_hash
            or not session.effective_terms_hash
            or not session.accounting_contract_hash
        ):
            raise ApprovedRuntimeDispatchError("Session contract is incomplete")

        provider = self.provider_inventory.store.get_provider_instance(
            binding.provider_instance_id
        )
        deployment = self.provider_inventory.store.get_model_deployment(
            binding.model_deployment_id
        )
        endpoint_url = provider.configuration.get("endpoint") or provider.configuration.get(
            "base_url"
        )
        if not isinstance(endpoint_url, str) or not endpoint_url:
            raise ApprovedRuntimeDispatchError("Provider Instance has no execution endpoint")

        contract = AccountingContract.model_validate(session.accounting_contract_snapshot)
        if contract.payload_hash != session.accounting_contract_hash:
            raise ApprovedRuntimeDispatchError("Session Accounting Contract hash mismatch")
        profile = self._usage_profile(binding)
        if profile.profile_hash != binding.usage_reporting_profile_hash:
            raise ApprovedRuntimeDispatchError("Runtime Binding Usage Profile mismatch")

        runtime_signature = binding.binding_hash()
        route = DispatcherRoute(
            destination_type="RUNTIME",
            destination_id=binding.runtime_id,
            route_type="REMOTE_RUNTIME",
            route_generation=1,
            runtime_generation=binding.runtime_generation,
            allowed_source_types={"HYPERVISOR"},
            allowed_channel_classes={"RUNTIME"},
            allowed_message_types={"RUNTIME_EXECUTE"},
            runtime_binding_hash=binding.binding_hash(),
            created_at=datetime.now(UTC).isoformat(),
        )
        protocol = RuntimeProtocolService(
            hypervisor_id=self.hypervisor_id,
            network_revision=self.network_revision,
            binding_resolver=lambda runtime_id: self._binding(binding, runtime_id),
            route_resolver=lambda runtime_id: route if runtime_id == binding.runtime_id else None,
            runtime_authenticator=lambda item: getattr(item, "runtime_signature", None)
            == runtime_signature,
            hypervisor_signer=lambda _: f"hypervisor:{self.hypervisor_id}",
            request_authorizer=lambda request: self._authorize_request(
                request, endpoint=endpoint, session=session
            ),
            accounting_contract_resolver=lambda contract_hash: self._contract(
                contract, contract_hash
            ),
            usage_profile_resolver=lambda runtime_id: self._profile(profile, runtime_id),
            store=self.runtime_protocol_store,
        )
        connection = self._connect(
            protocol=protocol,
            binding=binding,
            route=route,
            runtime_signature=runtime_signature,
        )
        payload_hash = canonical_hash(request_payload)
        runtime_timeout_seconds = _runtime_timeout_seconds(endpoint)
        request = RuntimeExecuteRequest(
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            runtime_configuration_hash=binding.runtime_configuration_hash,
            route_generation=route.route_generation,
            endpoint_id=endpoint.endpoint_id,
            endpoint_configuration_hash=endpoint.configuration_hash,
            session_id=session.session_id,
            session_contract_hash=session.session_contract_hash,
            effective_terms_hash=session.effective_terms_hash,
            request_id=request_id,
            capability_id=binding.capability_id,
            capability_version=binding.capability_version,
            capability_definition_hash=binding.capability_definition_hash,
            request_payload_hash=payload_hash,
            request_payload=request_payload,
            request_charge_ceiling=(
                session.request_charge_ceiling_q_atoms / 1_000_000
            ),
            accounting_contract_hash=session.accounting_contract_hash,
            idempotency_key=request_id,
            request_deadline=request_deadline
            or (
                datetime.now(UTC)
                + timedelta(
                    seconds=max(
                        _MIN_REQUEST_DEADLINE_SECONDS,
                        runtime_timeout_seconds + _REQUEST_DEADLINE_GRACE_SECONDS,
                    )
                )
            ).isoformat(),
        )
        adapter_class = {
            "llamacpp-openai": LlamaCppOpenAIAdapter,
            "ollama-generate": OllamaGenerateAdapter,
            "openai-tts": OpenAITtsAdapter,
            "proxy-openai": ProxyOpenAIAdapter,
            "vllm-openai": VllmOpenAIAdapter,
            "whisper-http": WhisperHttpAdapter,
        }[binding.adapter_id]
        adapter_kwargs = {
            "endpoint": endpoint_url,
            "model": deployment.provider_model_reference,
            "runtime_signature": runtime_signature,
            "timeout_seconds": runtime_timeout_seconds,
        }
        if binding.adapter_id == "whisper-http":
            adapter_kwargs["api_format"] = str(
                provider.configuration.get("api_format")
                or "whisper_asr_webservice"
            )
        if binding.adapter_id == "openai-tts":
            adapter_kwargs["voice"] = str(
                provider.configuration.get("voice") or "alloy"
            )
        adapter = adapter_class(**adapter_kwargs)
        if streaming and "streaming" not in binding.supported_features:
            raise ApprovedRuntimeDispatchError(
                f"Runtime Adapter {binding.adapter_id} does not support streaming"
            )
        if streaming:
            return adapter.execute_streaming(protocol, connection.runtime_connection_id, request)
        return adapter.execute(protocol, connection.runtime_connection_id, request)

    @staticmethod
    def _usage_profile(binding):
        if binding.adapter_id == "llamacpp-openai":
            return build_llamacpp_usage_profile(
                runtime_id=binding.runtime_id,
                runtime_generation=binding.runtime_generation,
                runtime_configuration_hash=binding.runtime_configuration_hash,
                adapter_version=binding.adapter_version or "llamacpp-openai.v1",
            )
        if binding.adapter_id == "ollama-generate":
            return build_ollama_usage_profile(
                runtime_id=binding.runtime_id,
                runtime_generation=binding.runtime_generation,
                runtime_configuration_hash=binding.runtime_configuration_hash,
                adapter_version=binding.adapter_version or "ollama-generate.v1",
            )
        if binding.adapter_id == "openai-tts":
            return build_tts_usage_profile(
                runtime_id=binding.runtime_id,
                runtime_generation=binding.runtime_generation,
                runtime_configuration_hash=binding.runtime_configuration_hash,
                adapter_version=binding.adapter_version or "openai-tts.v1",
            )
        if binding.adapter_id == "proxy-openai":
            return build_proxy_opaque_usage_profile(
                runtime_id=binding.runtime_id,
                runtime_generation=binding.runtime_generation,
                runtime_configuration_hash=binding.runtime_configuration_hash,
                adapter_version=binding.adapter_version or "proxy-openai.v1",
            )
        if binding.adapter_id == "whisper-http":
            return build_whisper_usage_profile(
                runtime_id=binding.runtime_id,
                runtime_generation=binding.runtime_generation,
                runtime_configuration_hash=binding.runtime_configuration_hash,
                adapter_version=binding.adapter_version or "whisper-http.v1",
            )
        return build_vllm_usage_profile(
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            runtime_configuration_hash=binding.runtime_configuration_hash,
            adapter_version=binding.adapter_version or "vllm-openai.v1",
        )

    @staticmethod
    def _binding(binding, runtime_id: str):
        if runtime_id != binding.runtime_id:
            raise KeyError(runtime_id)
        return binding

    @staticmethod
    def _contract(contract, contract_hash: str):
        if contract_hash != contract.payload_hash:
            raise KeyError(contract_hash)
        return contract

    @staticmethod
    def _profile(profile, runtime_id: str):
        if runtime_id != profile.runtime_id:
            raise KeyError(runtime_id)
        return profile

    @staticmethod
    def _authorize_request(request, *, endpoint, session) -> bool:
        return (
            request.endpoint_id == endpoint.endpoint_id
            and request.endpoint_configuration_hash == endpoint.configuration_hash
            and request.session_id == session.session_id
            and request.session_contract_hash == session.session_contract_hash
            and (
                request.effective_terms_hash is None
                or request.effective_terms_hash == session.effective_terms_hash
            )
            and request.accounting_contract_hash == session.accounting_contract_hash
        )

    @staticmethod
    def _connect(*, protocol, binding, route, runtime_signature: str):
        hello = RuntimeHello(
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            instance_id=f"adapter-{uuid4().hex}",
            runtime_configuration_hash=binding.runtime_configuration_hash,
            capability_id=binding.capability_id,
            supported_capability_versions=[binding.capability_version],
            supported_definition_hashes=[binding.capability_definition_hash],
            supported_runtime_protocol_versions=["1.0"],
            supported_runtime_features=list(binding.supported_features),
            adapter_id=binding.adapter_id,
            adapter_version=binding.adapter_version,
            runtime_nonce=uuid4().hex,
            runtime_challenge=uuid4().hex,
            runtime_signature=runtime_signature,
        )
        response = protocol.begin_handshake(hello)
        return protocol.complete_handshake(
            RuntimeHelloComplete(
                handshake_id=response.handshake_id,
                runtime_id=binding.runtime_id,
                runtime_generation=binding.runtime_generation,
                route_generation=route.route_generation,
                hypervisor_challenge_response=protocol.challenge_response(
                    response.hypervisor_challenge
                ),
                current_operational_state="READY",
                runtime_signature=runtime_signature,
            )
        )

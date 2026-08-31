"""Deterministic safety gates around Resident Steward language output.

The local model is an untrusted text generator.  This module deliberately
keeps high-risk intent detection and output validation outside the model so a
small or confused model cannot turn a chat answer into an authoritative action.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_SECRET_REQUEST_RE = re.compile(
    r"\b(?:private\s+key|secret\s+key|seed\s+phrase|recovery\s+seed|"
    r"mnemonic|password|passphrase|api\s*key|access\s+token|bearer\s+token|"
    r"credential(?:s)?|секрет(?:ы|ов)?|приватн(?:ый|ого)\s+ключ|сид\s+фраз)",
    re.IGNORECASE,
)
_MUTATION_REQUEST_RE = re.compile(
    r"(?:^|[.!?;]\s*)(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|"
    r"i\s+(?:need|want)\s+you\s+to\s+)?(?:restart|reboot|start|stop|install|"
    r"download|publish|expose|delete|remove|reset|apply|execute|sign|send|"
    r"configure|change|enable|disable)\b"
    r"|\b(?:please|can\s+you|could\s+you|would\s+you)\s+(?:restart|reboot|"
    r"start|stop|install|download|publish|expose|delete|remove|reset|apply|"
    r"execute|sign|send|configure|change|enable|disable)\b"
    r"|(?:^|[.!?;]\s*)(?:пожалуйста\s+|можешь\s+|можете\s+|сделай\s+|"
    r"выполни\s+)?(?:перезапусти|перезагрузи|запусти|останови|установи|скачай|"
    r"опубликуй|удали|сбрось|примени|выполни|подпиши|отправь|настрой|измени|"
    r"включи|выключи)\b",
    re.IGNORECASE,
)
_INJECTION_REQUEST_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?(?:previous|prior|above)|forget\s+your\s+instructions|"
    r"disregard\s+the\s+system|system\s+prompt|developer\s+message|"
    r"pretend\s+(?:that|you)|claim\s+that|say\s+that\s+you|"
    r"игнорируй\s+(?:все\s+)?(?:предыдущие|инструкции)|забудь\s+инструкции|"
    r"притворись|заяви,?\s+что)",
    re.IGNORECASE,
)
_SECRET_OUTPUT_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk|pk)-[A-Za-z0-9_-]{16,}|"
    r"\b(?:private|secret|api)[ _-]?key\s*[:=]\s*\S{12,}|"
    r"\bbearer\s+[A-Za-z0-9._-]{20,})",
    re.IGNORECASE,
)
_ACTION_CLAIM_RE = re.compile(
    r"(?:\b(?:i|we|assistant|steward|я|мы|агент)\s+(?:have\s+|has\s+|already\s+|"
    r"уже\s+)?(?:restarted|rebooted|started|stopped|installed|downloaded|"
    r"published|exposed|deleted|removed|reset|applied|executed|signed|sent|"
    r"configured|changed|enabled|disabled|перезапустил(?:а|и)?|перезагрузил(?:а|и)?|"
    r"запустил(?:а|и)?|остановил(?:а|и)?|установил(?:а|и)?|скачал(?:а|и)?|"
    r"опубликовал(?:а|и)?|удалил(?:а|и)?|сбросил(?:а|и)?|применил(?:а|и)?|"
    r"выполнил(?:а|и)?|подписал(?:а|и)?|отправил(?:а|и)?|настроил(?:а|и)?|"
    r"изменил(?:а|и)?|включил(?:а|и)?|выключил(?:а|и)?)\b"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StewardGuardDecision:
    """A deterministic classification made before model invocation."""

    intent: str
    blocked: bool
    code: str | None = None
    response: str | None = None
    requires_approval: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "blocked": self.blocked,
            "code": self.code,
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True)
class StewardOutputValidation:
    """Validation result for untrusted model output."""

    accepted: bool
    output_text: str
    code: str | None = None
    message: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class StewardDecision:
    """Deterministic read-only routing decision kept outside the local model."""

    intent: str
    tool: str | None
    approval: str
    escalate: bool

    def as_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "tool": {"name": self.tool, "arguments": {}} if self.tool else None,
            "approval": self.approval,
            "escalate": self.escalate,
        }


_EVENT_TO_TOOL = {
    "runtime_start_failed": "resource.inspect_pressure",
    "provider_exit": "provider.health_check",
    "endpoint_timeout": "endpoint.inspect_health",
    "endpoint_queue_overloaded": "endpoint.inspect_queue",
    "resource_warning": "resource.inspect_storage",
    "model_artifact_missing": "model.inspect_artifact",
    "bundle_validation_failed": "bundle.inspect_validation",
    "bundle_revalidation_required": "bundle.inspect_validation",
    "wallet_unavailable": "wallet.inspect_status",
    "peer_unavailable": "network.inspect_peer",
    "endpoint_validation_failed": "validation.inspect_report",
    "resource_lease_conflict": "resource.inspect_leases",
    "model_download_failed": "model.inspect_download",
    "model_checksum_failed": "model.verify_artifact",
    "endpoint_publication_requested": "endpoint.publish",
    "provider_installation_requested": "provider.install",
    "installation_state": "installation.inspect_next_step",
    "node_status": "node.inspect_status",
}


def _tool_from_message(message: str) -> str | None:
    text = str(message or "").lower()
    patterns = (
        (("ping", "пинг"), "node.inspect_status"),
        (("out of memory", "cuda oom", "vram", "ресурс", "ресурсов", "локальной модели"), "resource.inspect_pressure"),
        (("provider crashed", "provider health"), "provider.health_check"),
        (("endpoint", "timing out"), "endpoint.inspect_health"),
        (("queue", "overload"), "endpoint.inspect_queue"),
        (("disk", "storage"), "resource.inspect_storage"),
        (("model file", "artifact missing"), "model.inspect_artifact"),
        (("bundle", "validation"), "bundle.inspect_validation"),
        (("wallet", "кошел"), "wallet.inspect_status"),
        (("peer", "пир"), "network.inspect_peer"),
        (("lease",), "resource.inspect_leases"),
        (("download", "загруз"), "model.inspect_download"),
        (("checksum",), "model.verify_artifact"),
        (("next reviewed step", "следующ"), "installation.inspect_next_step"),
        (
            (
                "working on my node",
                "работает на моей ноде",
                "что сейчас настроено",
                "что настроено на этом узле",
                "состояние узла",
                "состояние ноды",
            ),
            "node.inspect_status",
        ),
    )
    for markers, tool in patterns:
        if any(marker in text for marker in markers):
            return tool
    return None


def build_steward_decision(
    message: str,
    *,
    guard: StewardGuardDecision,
    diagnostic_snapshot: Mapping[str, Any] | None = None,
) -> StewardDecision:
    """Select a reviewed inspection tool or escalation without model authority."""

    snapshot = diagnostic_snapshot if isinstance(diagnostic_snapshot, Mapping) else {}
    event_type = str(snapshot.get("event_type") or "").strip()
    if guard.intent in {"secret_request", "prompt_injection"}:
        return StewardDecision(guard.intent, None, "DENIED", False)
    tool = _EVENT_TO_TOOL.get(event_type) or _tool_from_message(message)
    if event_type == "operator_request" and bool(snapshot.get("data_loss")):
        tool = "node.factory_reset"
    if guard.requires_approval:
        return StewardDecision(guard.intent, tool, "OPERATOR_CONFIRMATION", False)
    # A missing deterministic route is not an escalation.  The local model
    # may still explain the bounded, secret-free context or select one of the
    # supplied Hypervisor tools.  It never receives arbitrary shell authority.
    if tool is None:
        return StewardDecision(guard.intent, None, "NONE", False)
    return StewardDecision(guard.intent, tool, "NONE", False)


def append_steward_decision(output_text: str, decision: StewardDecision) -> str:
    """Attach one canonical machine-readable decision to safe operator prose."""

    prose = str(output_text or "").strip()
    rendered = json.dumps(
        decision.as_payload(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{prose}\n{rendered}" if prose else rendered


def deterministic_steward_summary(
    message: str,
    *,
    decision: StewardDecision,
    diagnostic_snapshot: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> str:
    """Render a bounded evidence summary that remains useful without the SLM."""

    snapshot = diagnostic_snapshot if isinstance(diagnostic_snapshot, Mapping) else {}
    safe_context = context if isinstance(context, Mapping) else {}
    inference = safe_context.get("resident_inference")
    inference = inference if isinstance(inference, Mapping) else {}
    installation = safe_context.get("installation")
    installation = installation if isinstance(installation, Mapping) else {}
    next_action = installation.get("next_action")
    next_action = next_action if isinstance(next_action, Mapping) else {}
    event_type = str(snapshot.get("event_type") or "").strip()
    if event_type == "node_status" and re.search(r"[А-Яа-яЁё]", str(message or "")):
        return "Нода работает; доступны наблюдаемые статусы сервисов и локальной модели."
    english = {
        "runtime_start_failed": "The runtime start evidence reports an out of memory condition. Inspect current resource pressure before another start attempt.",
        "provider_exit": "The provider exited after being healthy. Inspect provider health and its bounded exit diagnostic.",
        "endpoint_timeout": "The endpoint has recent timeout evidence. Inspect endpoint health and queue pressure.",
        "endpoint_queue_overloaded": "The endpoint queue is overloaded. Inspect queued work and available concurrency.",
        "resource_warning": "The node reports low disk space. Inspect storage pressure before downloads or installs.",
        "model_artifact_missing": "The configured model artifact is missing. Inspect the reviewed model path and verification state.",
        "bundle_validation_failed": "The bundle failed validation. Inspect the validation report before publication or use.",
        "bundle_revalidation_required": "The bundle validation is stale. Inspect validation state before reuse.",
        "wallet_unavailable": "The operator wallet is unavailable. Inspect wallet status; secret material is not exposed here.",
        "peer_unavailable": "The peer is currently unavailable. Inspect peer reachability and last-seen evidence.",
        "endpoint_validation_failed": "Endpoint validation failed. Inspect the validation report and failed checks.",
        "resource_lease_conflict": "The model start conflicts with an active resource lease. Inspect leases and available capacity.",
        "model_download_failed": "The model download failed. Inspect the download status and reviewed source evidence.",
        "model_checksum_failed": "The model checksum does not match. Do not start it; inspect artifact verification evidence.",
        "installation_state": "The assisted installation has a reviewed next step. Inspect it before any state change.",
        "node_status": "The node status snapshot is available. Inspect observed service and inference state.",
    }
    if event_type in english:
        return english[event_type]
    if decision.tool == "node.inspect_status":
        state = str(inference.get("state") or "unknown")
        provider = str(inference.get("provider_type") or "unknown")
        if re.search(r"[А-Яа-яЁё]", str(message or "")):
            return f"Нода доступна. Локальная модель: {state}; провайдер: {provider}."
        return f"The node is available. Local model: {state}; provider: {provider}."
    if decision.tool == "installation.inspect_next_step":
        action = str(next_action.get("label") or next_action.get("id") or "operator review")
        if re.search(r"[А-Яа-яЁё]", str(message or "")):
            return f"Следующий проверенный шаг установки: {action}."
        return f"The next reviewed installation step is: {action}."
    if re.search(r"[А-Яа-яЁё]", str(message or "")):
        if decision.escalate:
            return "Доступных данных недостаточно для безопасного действия; нужна проверка оператора."
        return "Доступны только наблюдаемые данные ноды; выбран следующий безопасный шаг для проверки."
    if decision.escalate:
        return "The available evidence does not identify a safe action. Escalate for operator review."
    return "Only observed node evidence is available; use the selected read-only inspection step."


def steward_output_matches_language(message: str, output_text: str) -> bool:
    """Reject a non-Russian model answer when the operator wrote in Russian."""

    russian_request = bool(re.search(r"[А-Яа-яЁё]", str(message or "")))
    if not russian_request:
        return True
    return bool(re.search(r"[А-Яа-яЁё]", str(output_text or "")))


def classify_steward_request(message: str) -> StewardGuardDecision:
    """Classify high-risk Steward requests without asking the model."""

    text = str(message or "").strip()
    if _SECRET_REQUEST_RE.search(text):
        return StewardGuardDecision(
            intent="secret_request",
            blocked=True,
            code="STEWARD_SECRET_REQUEST_BLOCKED",
            response=(
                "I cannot reveal or reconstruct private keys, seed phrases, "
                "passwords, tokens, or other credentials. Use the local wallet "
                "backup or recovery procedure; secret material is not available "
                "to the Steward chat."
            ),
        )
    if _INJECTION_REQUEST_RE.search(text):
        return StewardGuardDecision(
            intent="prompt_injection",
            blocked=True,
            code="STEWARD_PROMPT_INJECTION_BLOCKED",
            response=(
                "I cannot override the Steward safety rules or claim that an "
                "action happened without an observed Hypervisor result. I can "
                "describe the current state or prepare the next reviewed step."
            ),
        )
    if _MUTATION_REQUEST_RE.search(text):
        return StewardGuardDecision(
            intent="mutation_request",
            # The action policy, not a blanket chat refusal, decides whether a
            # reviewed tool is automatic, asks the operator, or is denied.
            # Secret and prompt-injection requests above remain hard-blocked.
            blocked=False,
            code="STEWARD_MUTATION_POLICY_CONTROLLED",
        )
    return StewardGuardDecision(intent="information_request", blocked=False)


def validate_steward_output(output_text: str, *, fallback: str) -> StewardOutputValidation:
    """Reject secret-shaped or unobserved action claims from the model."""

    rendered = str(output_text or "").strip()
    if not rendered:
        return StewardOutputValidation(
            accepted=False,
            output_text=fallback,
            code="STEWARD_EMPTY_OUTPUT",
            message="The model returned no operator-facing text.",
        )
    if _SECRET_OUTPUT_RE.search(rendered):
        return StewardOutputValidation(
            accepted=False,
            output_text=fallback,
            code="STEWARD_SECRET_OUTPUT_BLOCKED",
            message="The model output matched a secret-shaped pattern.",
        )
    if _ACTION_CLAIM_RE.search(rendered):
        return StewardOutputValidation(
            accepted=False,
            output_text=fallback,
            code="STEWARD_UNOBSERVED_ACTION_CLAIM",
            message="The model claimed a state change without an authoritative result.",
        )
    return StewardOutputValidation(accepted=True, output_text=rendered)


__all__ = [
    "StewardDecision",
    "StewardGuardDecision",
    "StewardOutputValidation",
    "append_steward_decision",
    "build_steward_decision",
    "classify_steward_request",
    "deterministic_steward_summary",
    "steward_output_matches_language",
    "validate_steward_output",
]

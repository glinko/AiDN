"""Deterministic safety gates around Resident Steward language output.

The local model is an untrusted text generator.  This module deliberately
keeps high-risk intent detection and output validation outside the model so a
small or confused model cannot turn a chat answer into an authoritative action.
"""

from __future__ import annotations

import re
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
    r"|\b(?:the\s+)?(?:node|model|provider|service|runtime|endpoint|installation|"
    r"wallet)\s+(?:has\s+been|was|were|is|are)?\s*(?:restarted|rebooted|"
    r"started|stopped|installed|downloaded|published|exposed|deleted|removed|"
    r"reset|applied|executed|signed|sent|configured|changed|enabled|disabled)\b"
    r"|\b(?:перезапущен(?:а|о|ы)?|перезагружен(?:а|о|ы)?|запущен(?:а|о|ы)?|"
    r"остановлен(?:а|о|ы)?|установлен(?:а|о|ы)?|скачан(?:а|о|ы)?|опубликован(?:а|о|ы)?|"
    r"удален(?:а|о|ы)?|сброшен(?:а|о|ы)?|применен(?:а|о|ы)?|выполнен(?:а|о|ы)?|"
    r"подписан(?:а|о|ы)?|отправлен(?:а|о|ы)?|настроен(?:а|о|ы)?|изменен(?:а|о|ы)?|"
    r"включен(?:а|о|ы)?|выключен(?:а|о|ы)?)\b)",
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
            blocked=True,
            code="STEWARD_MUTATION_REQUIRES_APPROVAL",
            requires_approval=True,
            response=(
                "I did not change the node. Restart, installation, download, "
                "publication, network exposure and other state changes require "
                "an explicit AiDN review and operator approval. I can explain "
                "the safe next step or show the current observed state."
            ),
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
    "StewardGuardDecision",
    "StewardOutputValidation",
    "classify_steward_request",
    "validate_steward_output",
]

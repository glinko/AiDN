"""Minimal MCP control plane for the external Faucet Treasury service."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from aidn_faucet.models import (
    FaucetChallengeRequest,
    FaucetClaimRequest,
    FaucetLowBalanceRequest,
    FaucetPauseRequest,
)
from aidn_faucet.service import FaucetService

MCP_PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_MCP_PROTOCOL_VERSIONS = ("2025-03-26", "2025-06-18")
MCP_SERVER_VERSION = "0.1.0"
DEFAULT_MCP_SESSION_TTL_SECONDS = 3600

JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
MCP_AUTH_ERROR = -32001


def _now() -> datetime:
    return datetime.now(UTC)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"))
    return str(value)


def _json_text(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=True, sort_keys=True)


@dataclass(frozen=True)
class _McpSession:
    session_id: str
    role: str
    token_digest: str
    expires_at: datetime


@dataclass(frozen=True)
class _McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    roles: frozenset[str]
    handler: Callable[[dict[str, Any]], Any]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class FaucetMcpServer:
    """Token-separated MCP server for Faucet agents and creator controls.

    The server never returns the configured tokens, Treasury private key or a
    signed transfer envelope. Creator tools are deliberately not visible to an
    agent session authenticated with the agent token.
    """

    def __init__(
        self,
        service: FaucetService,
        *,
        agent_token: str | None = None,
        creator_token: str | None = None,
        session_ttl_seconds: int = DEFAULT_MCP_SESSION_TTL_SECONDS,
    ) -> None:
        if session_ttl_seconds < 60:
            raise ValueError("MCP session TTL must be at least 60 seconds")
        self.service = service
        self.agent_token = agent_token if agent_token is not None else service.agent_token
        self.creator_token = creator_token if creator_token is not None else service.creator_token
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, _McpSession] = {}
        self._lock = threading.RLock()
        self._tools = self._build_tools()

    def handle(
        self,
        request: dict[str, Any],
        *,
        token: str | None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return (
                self._error(
                    request.get("id") if isinstance(request, dict) else None,
                    JSONRPC_INVALID_REQUEST,
                    "Invalid JSON-RPC request",
                ),
                None,
            )
        method = request.get("method")
        request_id = request.get("id")
        if not isinstance(method, str):
            return self._error(request_id, JSONRPC_INVALID_REQUEST, "JSON-RPC method is required"), None
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self._error(request_id, JSONRPC_INVALID_PARAMS, "JSON-RPC params must be an object"), None

        try:
            if method == "initialize":
                return self._initialize(request_id, params, token)
            if method == "notifications/initialized":
                self._require_session(session_id, token)
                return None, session_id
            role = self._require_session(session_id, token)
            if method == "ping":
                return self._direct_result(request_id, {}), session_id
            if method == "tools/list":
                return self._direct_result(request_id, {"tools": self._tool_definitions(role)}), session_id
            if method == "tools/call":
                return self._call_tool(request_id, params, role), session_id
            if method == "resources/list":
                return self._direct_result(request_id, {"resources": self._resources(role)}), session_id
            if method == "resources/read":
                return self._read_resource(request_id, params, role), session_id
            return self._error(request_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}"), session_id
        except _McpAuthFailure as error:
            return self._error(request_id, MCP_AUTH_ERROR, str(error)), None
        except ValueError as error:
            return self._error(request_id, JSONRPC_INVALID_PARAMS, str(error)), session_id
        except Exception as error:  # pragma: no cover - defensive protocol boundary
            return self._error(request_id, JSONRPC_INTERNAL_ERROR, f"MCP internal error: {error}"), session_id

    def _initialize(
        self,
        request_id: Any,
        params: dict[str, Any],
        token: str | None,
    ) -> tuple[dict[str, Any], str]:
        role = self._authenticate(token)
        requested = params.get("protocolVersion", MCP_PROTOCOL_VERSION)
        protocol_version = requested if requested in SUPPORTED_MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        session = _McpSession(
            session_id="faucet-mcp-" + secrets.token_urlsafe(18),
            role=role,
            token_digest=self._token_digest(token),
            expires_at=_now() + timedelta(seconds=self.session_ttl_seconds),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return self._direct_result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {
                    "name": "aidn-faucet-control",
                    "version": MCP_SERVER_VERSION,
                },
            },
        ), session.session_id

    def _require_session(self, session_id: str | None, token: str | None) -> str:
        if not session_id:
            raise _McpAuthFailure("MCP session ID is required")
        role = self._authenticate(token)
        digest = self._token_digest(token)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise _McpAuthFailure("MCP session is not found")
            if session.token_digest != digest or session.role != role:
                raise _McpAuthFailure("MCP session token does not match")
            if _now() >= session.expires_at:
                self._sessions.pop(session_id, None)
                raise _McpAuthFailure("MCP session has expired")
            self._sessions[session_id] = _McpSession(
                session_id=session.session_id,
                role=session.role,
                token_digest=session.token_digest,
                expires_at=_now() + timedelta(seconds=self.session_ttl_seconds),
            )
        return role

    def _authenticate(self, token: str | None) -> str:
        if not token:
            raise _McpAuthFailure("MCP bearer token is required")
        if self.agent_token is not None and hmac.compare_digest(token, self.agent_token):
            return "agent"
        if self.creator_token is not None and hmac.compare_digest(token, self.creator_token):
            return "creator"
        raise _McpAuthFailure("MCP bearer token is invalid")

    @staticmethod
    def _token_digest(token: str | None) -> str:
        if token is None:
            return ""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _tool_definitions(self, role: str) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools if role in tool.roles]

    def _call_tool(self, request_id: Any, params: dict[str, Any], role: str) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._tool_result(
                request_id,
                {
                    "error": {
                        "code": "MCP_INVALID_ARGUMENTS",
                        "message": "Tool name and object arguments are required",
                    }
                },
                is_error=True,
            )
        tool = next((candidate for candidate in self._tools if candidate.name == name), None)
        if tool is None or role not in tool.roles:
            return self._tool_result(
                request_id,
                {
                    "error": {
                        "code": "MCP_PERMISSION_DENIED",
                        "message": "Tool is not available to this Faucet role",
                    }
                },
                is_error=True,
            )
        try:
            payload = _json_safe(tool.handler(arguments))
            return self._tool_result(request_id, payload)
        except ValueError as error:
            return self._tool_result(
                request_id,
                {"error": {"code": "FAUCET_OPERATION_REJECTED", "message": str(error)}},
                is_error=True,
            )

    def _resources(self, role: str) -> list[dict[str, Any]]:
        if role not in {"agent", "creator"}:
            return []
        return [
            {
                "uri": "aidn://faucet/status",
                "name": "Faucet status",
                "description": "Current policy, Treasury and control state without secret material.",
                "mimeType": "application/json",
            },
            {
                "uri": "aidn://faucet/policy",
                "name": "Faucet policy",
                "description": "Active replaceable payout policy identity and parameters.",
                "mimeType": "application/json",
            },
        ]

    def _read_resource(self, request_id: Any, params: dict[str, Any], role: str) -> dict[str, Any]:
        del role
        uri = params.get("uri")
        if not isinstance(uri, str):
            return self._error(request_id, JSONRPC_INVALID_PARAMS, "Resource URI is required")
        if uri == "aidn://faucet/status":
            return self._direct_result(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_text(self.service.status()),
                        }
                    ]
                },
            )
        if uri == "aidn://faucet/policy":
            return self._direct_result(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_text(
                                {
                                    "policy_id": self.service.policy.policy_id,
                                    "policy_version": self.service.policy.policy_version,
                                }
                            ),
                        }
                    ]
                },
            )
        return self._error(request_id, JSONRPC_INVALID_PARAMS, "Resource is not available")

    def _build_tools(self) -> tuple[_McpTool, ...]:
        object_schema = {"type": "object", "additionalProperties": True}
        return (
            _McpTool(
                "aidn.faucet.status",
                "Read Faucet policy, Treasury balance and safety controls.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                frozenset({"agent", "creator"}),
                lambda arguments: self.service.status(),
            ),
            _McpTool(
                "aidn.faucet.issue_challenge",
                "Issue a short-lived signed Wallet challenge for a Faucet claim.",
                {
                    "type": "object",
                    "required": ["wallet_id", "wallet_public_key"],
                    "properties": {"wallet_id": {"type": "string"}, "wallet_public_key": {"type": "string"}},
                    "additionalProperties": False,
                },
                frozenset({"agent"}),
                lambda arguments: self.service.issue_challenge(FaucetChallengeRequest.model_validate(arguments)),
            ),
            _McpTool(
                "aidn.faucet.claim",
                "Request a policy-approved Faucet payout from the dedicated Treasury.",
                object_schema,
                frozenset({"agent"}),
                lambda arguments: self.service.claim(FaucetClaimRequest.model_validate(arguments)),
            ),
            _McpTool(
                "aidn.faucet.reconcile",
                "Reconcile an existing claim without creating a replacement operation.",
                {
                    "type": "object",
                    "required": ["request_id"],
                    "properties": {"request_id": {"type": "string"}},
                    "additionalProperties": False,
                },
                frozenset({"agent"}),
                lambda arguments: self.service.reconcile(str(arguments["request_id"])),
            ),
            _McpTool(
                "aidn.faucet.admin.status",
                "Read creator control state and Faucet operational status.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                frozenset({"creator"}),
                lambda arguments: self.service.creator_status(),
            ),
            _McpTool(
                "aidn.faucet.admin.pause",
                "Pause new Faucet claims with an auditable operator reason.",
                {
                    "type": "object",
                    "required": ["reason"],
                    "properties": {"reason": {"type": "string", "minLength": 1}},
                    "additionalProperties": False,
                },
                frozenset({"creator"}),
                lambda arguments: self.service.pause(reason=FaucetPauseRequest.model_validate(arguments).reason),
            ),
            _McpTool(
                "aidn.faucet.admin.resume",
                "Resume Faucet claims after creator review.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                frozenset({"creator"}),
                lambda arguments: self.service.resume(),
            ),
            _McpTool(
                "aidn.faucet.admin.set_low_balance_watermark",
                "Set the Treasury balance below which new claims fail closed.",
                {
                    "type": "object",
                    "required": ["watermark_q_atoms"],
                    "properties": {"watermark_q_atoms": {"type": "integer", "minimum": 0}},
                    "additionalProperties": False,
                },
                frozenset({"creator"}),
                lambda arguments: self.service.set_low_balance_watermark(
                    watermark_q_atoms=FaucetLowBalanceRequest.model_validate(arguments).watermark_q_atoms
                ),
            ),
            _McpTool(
                "aidn.faucet.admin.claim_status",
                "Read sanitized state for one claim without returning the signed envelope.",
                {
                    "type": "object",
                    "required": ["request_id"],
                    "properties": {"request_id": {"type": "string"}},
                    "additionalProperties": False,
                },
                frozenset({"creator"}),
                lambda arguments: self.service.claim_status(str(arguments["request_id"])),
            ),
            _McpTool(
                "aidn.faucet.admin.reconcile_claim",
                "Reconcile one stored claim using its exact persisted operation.",
                {
                    "type": "object",
                    "required": ["request_id"],
                    "properties": {"request_id": {"type": "string"}},
                    "additionalProperties": False,
                },
                frozenset({"creator"}),
                lambda arguments: self.service.reconcile_as_creator(str(arguments["request_id"])),
            ),
        )

    @staticmethod
    def _direct_result(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _tool_result(request_id: Any, result: Any, *, is_error: bool = False) -> dict[str, Any]:
        content = [{"type": "text", "text": _json_text(result)}]
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": content,
                "structuredContent": result,
                "isError": is_error,
            },
        }

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class _McpAuthFailure(Exception):
    pass

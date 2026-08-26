"""Host-local commands for an AiDN Hypervisor operator."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from contextlib import contextmanager
from ipaddress import ip_address
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from aidn_hypervisor.config import load_operator_config
from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.network_profile import (
    NETWORK_PROFILE_ENV,
    NETWORK_PROFILE_SIGNERS_ENV,
    NetworkProfileError,
    activate_network_profile,
    load_network_profile,
    load_network_profile_signers,
    resolve_network_profile_path,
    verify_network_profile,
)
from aidn_hypervisor.secrets import FileSecretManager, SecretManagerError
from aidn_hypervisor.testnet_participation import (
    TestnetParticipationCalculator,
    load_testnet_participation_program,
)
from aidn_hypervisor.testnet_participation_evidence import (
    TestnetParticipationEvidenceStore,
)

_RUNTIME_ENVIRONMENT_KEYS = (
    "AIDN_HYPERVISOR_STATE_PATH",
    "AIDN_HYPERVISOR_BUNDLES_PATH",
    "AIDN_OPERATOR_API_URL",
    "AIDN_NODE_ID",
    "AIDN_OPERATOR_ID",
    "AIDN_CONSENSUS_MODE",
    "AIDN_COMETBFT_ENDPOINT",
    "AIDN_COMETBFT_CHAIN_ID",
    "AIDN_COMETBFT_SERVICE",
    "AIDN_COMETBFT_ABCI_STATE_PATH",
    "AIDN_COMETBFT_ABCI_HOST",
    "AIDN_COMETBFT_ABCI_PORT",
    "AIDN_SECRET_MANAGER_PATH",
    "AIDN_SECRET_MANAGER_MASTER_KEY",
    "AIDN_MCP_REMOTE_ENABLED",
    "AIDN_MCP_CONTROL_SESSION_AUTO_RENEW",
    "AIDN_MCP_CONTROL_SESSION_TTL_SECONDS",
    "AIDN_MCP_CONTROL_SESSION_STATELESS",
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    """Add options needed when a command must build the local Hypervisor."""
    parser.add_argument(
        "--state-path",
        default=None,
        help="Hypervisor state path (defaults to AIDN_HYPERVISOR_STATE_PATH)",
    )
    parser.add_argument(
        "--bundles-path",
        default=None,
        help="Bundle registry path (defaults to AIDN_HYPERVISOR_BUNDLES_PATH)",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="Local Hypervisor API URL (defaults to AIDN_OPERATOR_API_URL)",
    )
    parser.add_argument("--node-id", default=None)
    parser.add_argument("--operator-id", default=None)
    parser.add_argument(
        "--consensus-mode",
        choices=("disabled", "non_validator", "validator"),
        default=None,
    )
    parser.add_argument("--consensus-endpoint", default=None)
    parser.add_argument("--consensus-chain-id", default=None)
    parser.add_argument("--consensus-service", default=None)
    parser.add_argument("--consensus-abci-state-path", default=None)
    parser.add_argument("--consensus-abci-host", default=None)
    parser.add_argument("--consensus-abci-port", default=None)


def _add_secret_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--secret-manager-path", required=True)
    parser.add_argument("--master-key-file", required=True)


def _label_argument(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 128:
        raise argparse.ArgumentTypeError("--label must contain 1..128 characters")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate one local AiDN Hypervisor")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="create a one-time dashboard pairing code")
    _add_secret_options(pair)
    _add_runtime_options(pair)
    pair.add_argument("--dashboard-url", required=True)
    pair.add_argument("--ttl-seconds", type=int, default=600)

    wallet = commands.add_parser("wallet", help="inspect or bootstrap the owner wallet")
    wallet_commands = wallet.add_subparsers(dest="wallet_command", required=True)
    wallet_status = wallet_commands.add_parser("status", help="show public wallet state")
    _add_secret_options(wallet_status)
    _add_runtime_options(wallet_status)
    wallet_create = wallet_commands.add_parser("create", help="create the owner wallet once")
    _add_secret_options(wallet_create)
    _add_runtime_options(wallet_create)
    wallet_create.add_argument("--label", default=None, type=_label_argument)
    wallet_import = wallet_commands.add_parser("import", help="import an owner wallet from /dev/tty")
    _add_secret_options(wallet_import)
    _add_runtime_options(wallet_import)
    wallet_import.add_argument("--label", default=None, type=_label_argument)

    enrollment = commands.add_parser(
        "enrollment", help="inspect and approve existing MCP agent requests"
    )
    enrollment_commands = enrollment.add_subparsers(dest="enrollment_command", required=True)
    for name, help_text in (
        ("status", "show pending and completed agent requests"),
        ("list", "show pending and completed agent requests"),
    ):
        enrollment_status = enrollment_commands.add_parser(name, help=help_text)
        _add_secret_options(enrollment_status)
        _add_runtime_options(enrollment_status)
    for name, help_text in (
        ("approve", "approve one pending request for dashboard/MCP use"),
        ("reject", "reject one pending request"),
    ):
        enrollment_action = enrollment_commands.add_parser(name, help=help_text)
        _add_secret_options(enrollment_action)
        _add_runtime_options(enrollment_action)
        enrollment_action.add_argument("--request-id", required=True)

    network = commands.add_parser(
        "network", help="show, verify, or select the local Network Profile"
    )
    network.add_argument(
        "--profile-path",
        default=None,
        help=f"active Network Profile (defaults to {NETWORK_PROFILE_ENV})",
    )
    network.add_argument(
        "--trusted-signers-path",
        default=None,
        help=f"trusted authority registry (defaults to {NETWORK_PROFILE_SIGNERS_ENV})",
    )
    network_commands = network.add_subparsers(dest="network_command", required=True)
    network_commands.add_parser("show", help="show the selected profile and binding hash")
    network_commands.add_parser("verify", help="verify genesis and public-profile bindings")
    network_use = network_commands.add_parser("use", help="activate one verified profile")
    network_use.add_argument("name", help="profile name or TOML file path")
    network_use.add_argument(
        "--profiles-dir",
        default=None,
        help="directory containing <name>.toml profiles",
    )

    participation = commands.add_parser(
        "participation",
        help="inspect or reproduce a Testnet participation settlement",
    )
    participation.add_argument(
        "--program-path",
        required=True,
        help="reviewed Testnet participation TOML policy",
    )
    participation_commands = participation.add_subparsers(
        dest="participation_command", required=True
    )
    participation_commands.add_parser("verify", help="verify policy schema and show its hash")
    participation_calculate = participation_commands.add_parser(
        "calculate", help="calculate a non-emitting daily settlement from finalized evidence"
    )
    participation_calculate.add_argument("--evidence-store", required=True)
    participation_calculate.add_argument("--protocol-epoch", required=True, type=int)
    participation_calculate.add_argument("--source-epoch-transition-operation-id", required=True)
    participation_calculate.add_argument("--period-start", required=True)
    return parser


def _read_master_key(path_value: str) -> tuple[bytes, str]:
    try:
        encoded_key = Path(path_value).read_text(encoding="utf-8").strip()
        master_key = base64.b64decode(encoded_key, validate=True)
    except (OSError, ValueError) as exc:
        raise ValueError("master key file must contain base64-encoded key material") from exc
    if len(master_key) != 32:
        raise ValueError("master key must decode to exactly 32 bytes")
    return master_key, encoded_key


def _secret_manager(args: argparse.Namespace) -> FileSecretManager:
    master_key, _ = _read_master_key(args.master_key_file)
    return FileSecretManager(path=Path(args.secret_manager_path), master_key=master_key)


def _set_runtime_environment(args: argparse.Namespace) -> None:
    """Resolve command options into the same environment used by the service."""
    values = {
        "AIDN_HYPERVISOR_STATE_PATH": args.state_path,
        "AIDN_HYPERVISOR_BUNDLES_PATH": args.bundles_path,
        "AIDN_OPERATOR_API_URL": args.api_url,
        "AIDN_NODE_ID": args.node_id,
        "AIDN_OPERATOR_ID": args.operator_id,
        "AIDN_CONSENSUS_MODE": args.consensus_mode,
        "AIDN_COMETBFT_ENDPOINT": args.consensus_endpoint,
        "AIDN_COMETBFT_CHAIN_ID": args.consensus_chain_id,
        "AIDN_COMETBFT_SERVICE": args.consensus_service,
        "AIDN_COMETBFT_ABCI_STATE_PATH": args.consensus_abci_state_path,
        "AIDN_COMETBFT_ABCI_HOST": args.consensus_abci_host,
        "AIDN_COMETBFT_ABCI_PORT": args.consensus_abci_port,
    }
    for name, value in values.items():
        if value is not None:
            os.environ[name] = str(value)
    _, encoded_key = _read_master_key(args.master_key_file)
    os.environ["AIDN_SECRET_MANAGER_PATH"] = str(args.secret_manager_path)
    os.environ["AIDN_SECRET_MANAGER_MASTER_KEY"] = encoded_key
    # The same encrypted store backs dashboard access and MCP enrollment. This
    # only enables the credential-backed boundary; it does not mint a token.
    os.environ.setdefault("AIDN_MCP_REMOTE_ENABLED", "true")


@contextmanager
def _runtime_environment(args: argparse.Namespace):
    previous = {
        name: os.environ[name]
        for name in _RUNTIME_ENVIRONMENT_KEYS
        if name in os.environ
    }
    try:
        _set_runtime_environment(args)
    except Exception:
        for name in _RUNTIME_ENVIRONMENT_KEYS:
            os.environ.pop(name, None)
        os.environ.update(previous)
        raise
    try:
        yield
    finally:
        for name in _RUNTIME_ENVIRONMENT_KEYS:
            os.environ.pop(name, None)
        os.environ.update(previous)


def _require_state_path(args: argparse.Namespace) -> str:
    state_path = args.state_path or os.getenv("AIDN_HYPERVISOR_STATE_PATH")
    if not state_path:
        raise ValueError(
            "wallet commands require --state-path or AIDN_HYPERVISOR_STATE_PATH"
        )
    return state_path


def _bounded_json(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 64 * 1024:
        raise ValueError("command output exceeds the 64 KiB safety limit")
    return encoded


def _local_service(args: argparse.Namespace):
    _require_state_path(args)
    from aidn_hypervisor.main import build_app

    return build_app().state.hypervisor_service


def _api_url(args: argparse.Namespace) -> str | None:
    value = args.api_url or os.getenv("AIDN_OPERATOR_API_URL")
    if not value:
        return None
    value = value.rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--api-url must be an HTTP(S) loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--api-url must not contain credentials, query, or fragment data")
    hostname = parsed.hostname.lower().rstrip(".")
    is_loopback = hostname == "localhost"
    try:
        is_loopback = is_loopback or ip_address(hostname).is_loopback
    except ValueError:
        pass
    if not is_loopback:
        raise ValueError("--api-url must resolve to localhost or a loopback address")
    return value


def _api_request(
    args: argparse.Namespace,
    *,
    path: str,
    method: str,
    payload: dict | None = None,
) -> dict | None:
    """Use the already-running local service when available.

    A direct in-process fallback keeps ``--no-start`` and recovery operations
    usable. The bootstrap wrapper always points this at loopback, so wallet
    mutation stays inside the host boundary.
    """
    base = _api_url(args)
    if not base:
        return None
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base}{path}", data=body, headers=headers, method=method)
    try:
        opener = build_opener(_NoRedirect())
        with opener.open(request, timeout=3) as response:
            raw = response.read(64 * 1024 + 1)
    except HTTPError as exc:
        try:
            detail = exc.read(64 * 1024 + 1).decode("utf-8", errors="replace")
        except OSError:
            detail = ""
        raise RuntimeError(f"local Hypervisor API returned HTTP {exc.code}: {detail[:512]}") from exc
    except (URLError, TimeoutError, OSError):
        return None
    if len(raw) > 64 * 1024:
        raise RuntimeError("local Hypervisor API response exceeds the 64 KiB safety limit")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("local Hypervisor API returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("local Hypervisor API returned a non-object response")
    return decoded


def _wallet_command(args: argparse.Namespace) -> int:
    _require_state_path(args)
    if args.wallet_command == "status":
        api_result = _api_request(args, path="/operators/wallet/bootstrap", method="GET")
        if api_result is None:
            api_result = _local_service(args).owner_wallet_state()
        print(_bounded_json(api_result))
        return 0

    if args.wallet_command == "create":
        current_api_state = _api_request(
            args,
            path="/operators/wallet/bootstrap",
            method="GET",
        )
        if current_api_state is not None and current_api_state.get("configured"):
            print(
                _bounded_json(
                    {"status": "ALREADY_CONFIGURED", "wallet": current_api_state}
                )
            )
            return 0
        api_result = _api_request(
            args,
            path="/operators/wallet/bootstrap/create",
            method="POST",
            payload={"label": args.label},
        )
        if api_result is None:
            service = _local_service(args)
            current = service.owner_wallet_state()
            if current.get("configured"):
                api_result = {"status": "ALREADY_CONFIGURED", "wallet": current, "private_key": None}
            else:
                api_result = service.configure_owner_wallet(mode="create", label=args.label)
        if not isinstance(api_result, dict):
            raise RuntimeError("wallet create returned an invalid result")
        print(_bounded_json(api_result))
        if api_result.get("private_key"):
            print(
                "Save this one-time owner wallet private key in an approved secret store; "
                "it will not be shown again.",
                file=sys.stderr,
            )
        return 0

    if args.wallet_command == "import":
        api_result = _api_request(
            args,
            path="/operators/wallet/bootstrap",
            method="GET",
        )
        if api_result is not None and api_result.get("configured"):
            print(_bounded_json({"status": "ALREADY_CONFIGURED", "wallet": api_result}))
            return 0
        if api_result is None:
            service = _local_service(args)
            current = service.owner_wallet_state()
            if current.get("configured"):
                print(_bounded_json({"status": "ALREADY_CONFIGURED", "wallet": current}))
                return 0
        private_key = getpass.getpass("Owner wallet private key (hidden): ").strip()
        if not private_key:
            raise ValueError("owner wallet private key must not be empty")
        try:
            api_result = _api_request(
                args,
                path="/operators/wallet/bootstrap/import",
                method="POST",
                payload={"private_key": private_key, "label": args.label},
            )
            if api_result is None:
                api_result = _local_service(args).configure_owner_wallet(
                    mode="import", private_key=private_key, label=args.label
                )
        finally:
            # Do not retain the imported key in a module-level/global variable.
            private_key = ""
        print(_bounded_json(api_result))
        return 0
    raise ValueError(f"unsupported wallet command: {args.wallet_command}")


def _enrollment_command(args: argparse.Namespace) -> int:
    manager = _secret_manager(args)
    service = McpEnrollmentService(
        secret_manager=manager,
        credential_store=McpCredentialStore(secret_manager=manager),
    )
    if args.enrollment_command in {"status", "list"}:
        payload = {"items": [item.__dict__ for item in service.list_requests()]}
    elif args.enrollment_command == "approve":
        payload = service.approve(args.request_id).__dict__
    elif args.enrollment_command == "reject":
        payload = service.reject(args.request_id).__dict__
    else:
        raise ValueError(f"unsupported enrollment command: {args.enrollment_command}")
    print(_bounded_json(payload))
    return 0


def _network_command(args: argparse.Namespace) -> int:
    selected = resolve_network_profile_path(args.profile_path)
    trusted_signers = load_network_profile_signers(
        args.trusted_signers_path or os.getenv(NETWORK_PROFILE_SIGNERS_ENV)
    )
    if args.network_command == "use":
        if selected is None:
            raise ValueError(
                "network use requires --profile-path or AIDN_NETWORK_PROFILE_PATH"
            )
        candidate = Path(args.name).expanduser()
        if candidate.suffix.lower() != ".toml":
            profiles_dir = (
                Path(args.profiles_dir).expanduser()
                if args.profiles_dir
                else selected.parent / "network-profiles"
            )
            candidate = profiles_dir / f"{args.name}.toml"
        result = activate_network_profile(
            candidate,
            selected,
            trusted_profile_signers=trusted_signers,
        )
        print(_bounded_json(result.model_dump(mode="json")))
        return 0
    if selected is None:
        raise ValueError(
            "network command requires --profile-path or AIDN_NETWORK_PROFILE_PATH"
        )
    if args.network_command == "verify":
        result = verify_network_profile(
            selected, trusted_profile_signers=trusted_signers
        )
        print(_bounded_json(result.model_dump(mode="json")))
        return 0 if result.valid else 2
    if args.network_command == "show":
        profile = load_network_profile(selected)
        payload = profile.model_dump(mode="json")
        payload["profile_path"] = str(selected)
        payload["consensus_binding_hash"] = profile.consensus_binding_hash
        print(_bounded_json(payload))
        return 0
    raise ValueError(f"unsupported network command: {args.network_command}")


def _participation_command(args: argparse.Namespace) -> int:
    program = load_testnet_participation_program(args.program_path)
    if args.participation_command == "verify":
        print(
            _bounded_json(
                {
                    "program": program.model_dump(mode="json"),
                    "policy_hash": program.policy_hash,
                }
            )
        )
        return 0
    if args.participation_command == "calculate":
        evidence_store = TestnetParticipationEvidenceStore(args.evidence_store)
        enrollments, heartbeats = evidence_store.settlement_inputs(
            program,
            period_start=args.period_start,
        )
        settlement = TestnetParticipationCalculator().calculate(
            program,
            protocol_epoch=args.protocol_epoch,
            source_epoch_transition_operation_id=(
                args.source_epoch_transition_operation_id
            ),
            period_start=args.period_start,
            enrollments=enrollments,
            heartbeats=heartbeats,
        )
        print(_bounded_json(settlement.model_dump(mode="json")))
        return 0
    raise ValueError(f"unsupported participation command: {args.participation_command}")


def main(argv: list[str] | None = None) -> int:
    """Execute a local operator command without persisting secret values."""
    args = _build_parser().parse_args(argv)
    try:
        # An explicit recovery target must remain usable even when the
        # currently selected profile is invalid. Other commands consume the
        # normal operator/network configuration before doing any work.
        if not (args.command == "network" and args.profile_path is not None):
            load_operator_config()
        if args.command == "pair":
            if args.ttl_seconds <= 0:
                raise ValueError("--ttl-seconds must be positive")
            manager = _secret_manager(args)
            pairing = McpCredentialStore(secret_manager=manager).create_pairing_code(
                ttl_seconds=args.ttl_seconds
            )
            print("Dashboard pairing code created.")
            print(f"Open: {args.dashboard_url}")
            print(f"Expires: {pairing.expires_at}")
            print(f"Code: {pairing.code}")
            return 0
        if args.command == "wallet":
            with _runtime_environment(args):
                return _wallet_command(args)
        if args.command == "enrollment":
            return _enrollment_command(args)
        if args.command == "network":
            return _network_command(args)
        if args.command == "participation":
            return _participation_command(args)
        raise ValueError(f"unsupported command: {args.command}")
    except (OSError, RuntimeError, SecretManagerError, NetworkProfileError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())

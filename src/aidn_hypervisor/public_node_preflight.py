"""Read-only admission checks for a public AiDN Testnet host.

This is deliberately a host readiness report, not a deployment action.  It
cannot open firewall ports, obtain certificates, or claim that a cloud security
group is correct.  Those actions belong to the operator; the resulting report
makes each requirement explicit before a validator is installed.
"""

from __future__ import annotations

from ipaddress import IPv4Address, ip_address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PUBLIC_NODE_PREFLIGHT_VERSION = "aidn.public-node-preflight.v1"
GIB = 1024**3


class PublicNodeRequirements(BaseModel, frozen=True):
    """Minimum reviewed host envelope for the first public Testnet."""

    model_config = ConfigDict(extra="forbid")

    minimum_cpu_cores: int = Field(default=2, ge=1, le=1_024)
    minimum_memory_bytes: int = Field(default=4 * GIB, ge=GIB)
    minimum_free_disk_bytes: int = Field(default=40 * GIB, ge=GIB)
    required_os_id: str = "ubuntu"
    minimum_os_version: tuple[int, int] = (24, 4)


class PublicNodeHostObservation(BaseModel, frozen=True):
    """Facts collected locally or injected by the narrow host wrapper."""

    model_config = ConfigDict(extra="forbid")

    os_id: str
    os_version_id: str
    cpu_cores: int = Field(ge=0)
    memory_bytes: int = Field(ge=0)
    free_disk_bytes: int = Field(ge=0)
    p2p_port: int = Field(ge=1, le=65_535)
    p2p_port_available: bool
    time_synchronized: bool
    public_ipv4: str | None = None
    external_p2p_firewall_confirmed: bool = False
    api_exposure: Literal["loopback", "public_https"] = "loopback"
    public_dns_name: str | None = None
    tls_termination: str | None = None


class PublicNodePreflightCheck(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    status: Literal["PASS", "FAIL"]
    detail: str


class PublicNodePreflightReport(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PUBLIC_NODE_PREFLIGHT_VERSION
    status: Literal["PASS", "FAIL"]
    p2p_port: int
    checks: tuple[PublicNodePreflightCheck, ...]
    limitations: tuple[str, ...]


def _version_at_least(value: str, minimum: tuple[int, int]) -> bool:
    parts = value.split(".")
    try:
        actual = (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (IndexError, ValueError):
        return False
    return actual >= minimum


def _is_global_ipv4(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = ip_address(value)
    except ValueError:
        return False
    return isinstance(parsed, IPv4Address) and parsed.is_global


def evaluate_public_node_preflight(
    observation: PublicNodeHostObservation,
    *,
    requirements: PublicNodeRequirements | None = None,
) -> PublicNodePreflightReport:
    """Evaluate immutable host observations without making host changes."""

    required = requirements or PublicNodeRequirements()
    checks = (
        PublicNodePreflightCheck(
            check_id="SUPPORTED_UBUNTU",
            status=(
                "PASS"
                if observation.os_id.lower() == required.required_os_id
                and _version_at_least(observation.os_version_id, required.minimum_os_version)
                else "FAIL"
            ),
            detail=(
                f"requires {required.required_os_id} "
                f">={required.minimum_os_version[0]}.{required.minimum_os_version[1]:02d}; "
                f"observed {observation.os_id} {observation.os_version_id}"
            ),
        ),
        PublicNodePreflightCheck(
            check_id="CPU_CAPACITY",
            status="PASS" if observation.cpu_cores >= required.minimum_cpu_cores else "FAIL",
            detail=(
                f"requires >= {required.minimum_cpu_cores} CPU cores; "
                f"observed {observation.cpu_cores}"
            ),
        ),
        PublicNodePreflightCheck(
            check_id="MEMORY_CAPACITY",
            status="PASS" if observation.memory_bytes >= required.minimum_memory_bytes else "FAIL",
            detail=(
                f"requires >= {required.minimum_memory_bytes // GIB} GiB RAM; "
                f"observed {observation.memory_bytes / GIB:.2f} GiB"
            ),
        ),
        PublicNodePreflightCheck(
            check_id="DISK_CAPACITY",
            status="PASS" if observation.free_disk_bytes >= required.minimum_free_disk_bytes else "FAIL",
            detail=(
                f"requires >= {required.minimum_free_disk_bytes // GIB} GiB free disk; "
                f"observed {observation.free_disk_bytes / GIB:.2f} GiB"
            ),
        ),
        PublicNodePreflightCheck(
            check_id="TIME_SYNCHRONIZED",
            status="PASS" if observation.time_synchronized else "FAIL",
            detail="NTP/system clock synchronization must be active before consensus starts",
        ),
        PublicNodePreflightCheck(
            check_id="P2P_PORT_AVAILABLE",
            status="PASS" if observation.p2p_port_available else "FAIL",
            detail=f"local TCP port {observation.p2p_port} must be free for CometBFT P2P",
        ),
        PublicNodePreflightCheck(
            check_id="PUBLIC_IPV4",
            status="PASS" if _is_global_ipv4(observation.public_ipv4) else "FAIL",
            detail="a global public IPv4 address must be declared for this public node",
        ),
        PublicNodePreflightCheck(
            check_id="EXTERNAL_P2P_FIREWALL",
            status="PASS" if observation.external_p2p_firewall_confirmed else "FAIL",
            detail=(
                f"operator must confirm TCP/{observation.p2p_port} is allowed by the "
                "cloud/security-group firewall; local inspection cannot prove it"
            ),
        ),
        PublicNodePreflightCheck(
            check_id="PUBLIC_API_TLS",
            status=(
                "PASS"
                if observation.api_exposure == "loopback"
                or (bool(observation.public_dns_name) and bool(observation.tls_termination))
                else "FAIL"
            ),
            detail=(
                "loopback API needs no public TLS endpoint"
                if observation.api_exposure == "loopback"
                else "public API exposure requires DNS and an explicit TLS termination boundary"
            ),
        ),
    )
    return PublicNodePreflightReport(
        status="PASS" if all(check.status == "PASS" for check in checks) else "FAIL",
        p2p_port=observation.p2p_port,
        checks=checks,
        limitations=(
            "This report does not test Internet reachability; run the multi-node deployment acceptance after installation.",
            "This report does not alter operating-system, cloud-firewall, DNS, TLS, or CometBFT state.",
        ),
    )


__all__ = [
    "GIB",
    "PUBLIC_NODE_PREFLIGHT_VERSION",
    "PublicNodeHostObservation",
    "PublicNodePreflightCheck",
    "PublicNodePreflightReport",
    "PublicNodeRequirements",
    "evaluate_public_node_preflight",
]

from __future__ import annotations

from aidn_hypervisor.public_node_preflight import (
    GIB,
    PublicNodeHostObservation,
    evaluate_public_node_preflight,
)


def _observation(**updates: object) -> PublicNodeHostObservation:
    values: dict[str, object] = {
        "os_id": "ubuntu",
        "os_version_id": "24.04",
        "cpu_cores": 2,
        "memory_bytes": 4 * GIB,
        "free_disk_bytes": 40 * GIB,
        "p2p_port": 26656,
        "p2p_port_available": True,
        "time_synchronized": True,
        "public_ipv4": "8.8.8.8",
        "external_p2p_firewall_confirmed": True,
        "api_exposure": "loopback",
    }
    values.update(updates)
    return PublicNodeHostObservation.model_validate(values)


def test_public_node_preflight_accepts_supported_private_api_host() -> None:
    report = evaluate_public_node_preflight(_observation())

    assert report.status == "PASS"
    assert all(check.status == "PASS" for check in report.checks)


def test_public_node_preflight_fails_closed_for_missing_external_boundary() -> None:
    report = evaluate_public_node_preflight(
        _observation(
            time_synchronized=False,
            p2p_port_available=False,
            external_p2p_firewall_confirmed=False,
            public_ipv4="192.168.88.127",
            api_exposure="public_https",
        )
    )
    failed = {check.check_id for check in report.checks if check.status == "FAIL"}

    assert report.status == "FAIL"
    assert {"TIME_SYNCHRONIZED", "P2P_PORT_AVAILABLE", "PUBLIC_IPV4", "EXTERNAL_P2P_FIREWALL", "PUBLIC_API_TLS"} <= failed


def test_public_node_preflight_requires_ubuntu_2404_or_newer() -> None:
    report = evaluate_public_node_preflight(_observation(os_id="amzn", os_version_id="2023"))

    check = next(item for item in report.checks if item.check_id == "SUPPORTED_UBUNTU")
    assert check.status == "FAIL"

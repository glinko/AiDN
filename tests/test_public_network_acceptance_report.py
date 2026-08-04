from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/build-public-network-acceptance-report.py"
SPEC = importlib.util.spec_from_file_location("public_network_acceptance_report", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _source_reports(tmp_path: Path, *, ownership_status: str) -> tuple[Path, Path, Path]:
    lan = _write(
        tmp_path / "lan.json",
        {"status": "ok", "scope": "CONTROLLED_LAN_TESTNET"},
    )
    external = _write(
        tmp_path / "external.json",
        {
            "status": "ok",
            "rpc_endpoints": ["https://rpc-a.example", "https://rpc-b.example"],
            "finality_evidence": {
                "operation_id": "operation-1",
                "chain_id": "aidn-testnet-1",
                "block_height": 2,
                "block_id": "b" * 64,
                "app_hash": "c" * 64,
                "commit_hash": "d" * 64,
                "finalized_at": "2030-01-01T00:00:01Z",
                "verifier_id": "g4-verifier",
                "proof_version": "consensus-finality-evidence.v1",
            },
            "ownership_evidence": {
                "status": ownership_status,
                **(
                    {"ownership_evidence_root": "sha256:" + "a" * 64}
                    if ownership_status == "OUT_OF_BAND_VERIFIED"
                    else {}
                ),
            },
        },
    )
    deployment = _write(
        tmp_path / "deployment.json",
        {
            "status": "ok",
            "scope": "PUBLIC_NETWORK_DEPLOYMENT",
            "checks": {
                "public_p2p_acceptance": {
                    "status": "PASS",
                    "evidence_reference": "sha256:" + "1" * 64,
                },
                "bootstrap_diversity": {
                    "status": "PASS",
                    "evidence_reference": "sha256:" + "2" * 64,
                },
                "tls_validated": {
                    "status": "PASS",
                    "evidence_reference": "sha256:" + "3" * 64,
                },
            }
        },
    )
    return lan, external, deployment


def test_public_network_report_is_structurally_ok_but_incomplete_without_review(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_DECLARED")

    report = MODULE.build_report(
        lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
    )

    assert report["status"] == "ok"
    assert report["gate_status"] == "INCOMPLETE"
    assert all(check["status"] == "PASS" for check in report["checks"].values())


def test_public_network_report_passes_after_independence_review(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")

    report = MODULE.build_report(
        lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
    )

    assert report["status"] == "ok"
    assert report["gate_status"] == "PASS"


def test_public_network_report_rejects_unreferenced_boolean_check(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")
    deployment = json.loads(paths[2].read_text(encoding="utf-8"))
    deployment["checks"]["tls_validated"] = True
    paths[2].write_text(json.dumps(deployment), encoding="utf-8")

    with pytest.raises(ValueError, match="PASS object with evidence_reference"):
        MODULE.build_report(
            lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
        )


def test_public_network_report_rejects_failed_deployment_check(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")
    deployment = json.loads(paths[2].read_text(encoding="utf-8"))
    deployment["checks"]["public_p2p_acceptance"]["status"] = "FAIL"
    paths[2].write_text(json.dumps(deployment), encoding="utf-8")

    with pytest.raises(ValueError, match="status PASS"):
        MODULE.build_report(
            lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
        )


def test_public_network_report_rejects_unbound_check_reference(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")
    deployment = json.loads(paths[2].read_text(encoding="utf-8"))
    deployment["checks"]["tls_validated"]["evidence_reference"] = "tls.json"
    paths[2].write_text(json.dumps(deployment), encoding="utf-8")

    with pytest.raises(ValueError, match="valid evidence_reference"):
        MODULE.build_report(
            lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
        )


def test_public_network_report_rejects_verified_ownership_without_root(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")
    external = json.loads(paths[1].read_text(encoding="utf-8"))
    external["ownership_evidence"].pop("ownership_evidence_root")
    paths[1].write_text(json.dumps(external), encoding="utf-8")

    with pytest.raises(ValueError, match="ownership_evidence_root"):
        MODULE.build_report(
            lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
        )


def test_public_network_report_rejects_credentialed_rpc_endpoint(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")
    external = json.loads(paths[1].read_text(encoding="utf-8"))
    external["rpc_endpoints"][0] = "https://user:secret@rpc-a.example"
    paths[1].write_text(json.dumps(external), encoding="utf-8")

    with pytest.raises(ValueError, match="credential-free HTTPS"):
        MODULE.build_report(
            lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
        )


def test_public_network_report_rejects_truncated_finality_evidence(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")
    external = json.loads(paths[1].read_text(encoding="utf-8"))
    external["finality_evidence"] = {"operation_id": "operation-1"}
    paths[1].write_text(json.dumps(external), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required fields"):
        MODULE.build_report(
            lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
        )


def test_public_network_report_cli_uses_gate_status_for_exit_code(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")
    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--lan-report",
            str(paths[0]),
            "--external-report",
            str(paths[1]),
            "--deployment-report",
            str(paths[2]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["gate_status"] == "PASS"

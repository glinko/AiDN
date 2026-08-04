from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.snapshot_acceptance import run_snapshot_acceptance
from aidn_hypervisor.evidence import canonical_json_bytes, evidence_root

ROOT = Path(__file__).resolve().parents[1]
GATE_TOOL = ROOT / "tools/verify-release-gates.py"


def _run_gate(*extra: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            str(GATE_TOOL),
            "--profile",
            str(ROOT / "profiles/aidn-mainnet-candidate-1.json"),
            "--fixture-manifest",
            str(ROOT / "fixtures/manifest.json"),
            *extra,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _report_hash(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _write_g1_report(path: Path) -> None:
    profile = json.loads((ROOT / "profiles/aidn-mainnet-candidate-1.json").read_text(encoding="utf-8"))
    fixture_manifest = ROOT / "fixtures/manifest.json"
    checks = {
        name: {"status": "PASS", "evidence": "tests/consensus/test_release_conformance.py"}
        for name in (
            "unit_tests",
            "fix_0001_fixtures",
            "strict_operation_coverage",
            "unknown_operation_rejection",
            "unsupported_operation_version",
            "duplicate_operation_idempotency",
            "predecessor_mismatch",
            "monetary_boundaries",
            "canonical_json_hash_vectors",
        )
    }
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "profile_id": profile["profile_id"],
        "profile_commitment": profile["profile_commitment"],
        "fixture_manifest_hash": "sha256:" + hashlib.sha256(fixture_manifest.read_bytes()).hexdigest(),
        "checks": checks,
    }
    payload["report_hash"] = _report_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_g0_report(path: Path, artifact_root: Path) -> None:
    profile = json.loads((ROOT / "profiles/aidn-mainnet-candidate-1.json").read_text(encoding="utf-8"))
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact = artifact_root / "aidn-hypervisor-0.1.0.whl"
    source = artifact_root / "aidn-hypervisor-0.1.0.tar.gz"
    artifact.write_bytes(b"wheel")
    source.write_bytes(b"source")
    artifacts = [
        {
            "path": str(item.resolve()),
            "sha256": "sha256:" + hashlib.sha256(item.read_bytes()).hexdigest(),
        }
        for item in (artifact, source)
    ]
    manifest_payload = {
        "schema_version": 1,
        "release_id": "test-release",
        "source_commit": "a" * 40,
        "profile_id": profile["profile_id"],
        "profile_commitment": profile["profile_commitment"],
        "operation_catalog_hash": profile["operation_catalog"]["operation_catalog_hash"],
        "fixture_manifest_path": str((ROOT / "fixtures/manifest.json").resolve()),
        "fixture_manifest_hash": "sha256:" + hashlib.sha256(
            (ROOT / "fixtures/manifest.json").read_bytes()
        ).hexdigest(),
        "artifacts": artifacts,
    }
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    release_manifest = {
        "payload": manifest_payload,
        "payload_hash": _report_hash(manifest_payload),
        "signer_public_key": "ed25519:" + public_key.hex(),
        "signature": "ed25519:" + private_key.sign(canonical_json_bytes(manifest_payload)).hex(),
    }
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "profile_id": profile["profile_id"],
        "profile_commitment": profile["profile_commitment"],
        "checks": {
            "provenance_build": True,
            "package_hashes": True,
            "signed_release_manifest": True,
            "implementation_profile": True,
            "operation_catalog": True,
            "fixture_manifest": True,
            "dependency_license_scan": True,
        },
        "release_manifest": release_manifest,
    }
    payload["report_hash"] = _report_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_release_gate_requires_g0_and_g1_evidence_reports() -> None:
    result = _run_gate("--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["status"] == "INCOMPLETE"
    assert payload["gates"]["G0"]["status"] == "INCOMPLETE"
    assert payload["gates"]["G1"]["status"] == "INCOMPLETE"
    assert payload["gates"]["G2"]["status"] == "NOT_RUN"


def test_release_gate_fails_closed_without_allow_incomplete() -> None:
    result = _run_gate()
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["status"] == "INCOMPLETE"
    assert payload["gates"]["G1"]["status"] == "INCOMPLETE"


def test_release_gate_accepts_verified_g0_and_g1_reports(tmp_path: Path) -> None:
    g0_path = tmp_path / "g0-report.json"
    g1_path = tmp_path / "g1-report.json"
    _write_g0_report(g0_path, tmp_path / "artifacts")
    _write_g1_report(g1_path)

    result = _run_gate(
        "--g0-report",
        str(g0_path),
        "--g1-report",
        str(g1_path),
        "--allow-incomplete",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G0"]["status"] == "PASS"
    assert payload["gates"]["G1"]["status"] == "PASS"


def test_release_gate_accepts_verified_controlled_local_g2_report(tmp_path: Path) -> None:
    report_path = tmp_path / "g2-report.json"
    report_path.write_text(
        json.dumps(run_snapshot_acceptance(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = _run_gate("--g2-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G2"]["status"] == "PASS"
    assert payload["gates"]["G2"]["details"]["mode"] == "CONTROLLED_LOCAL"


def _g3_report(*, restart_status: str = "PASS", offline_status: str = "PASS") -> dict:
    snapshots = [
        {
            "rpc_url": f"http://validator-{index}",
            "height": 100,
            "app_hash": "A" * 64,
            "node_id": f"node-{index}",
            "chain_id": "chain-test",
        }
        for index in range(4)
    ]
    return {
        "status": "ok",
        "scope": "CONTROLLED_LAN_TESTNET",
        "strict_operation_coverage_probe": {"code": 1},
        "operations": [
            {"transaction_hash": f"{index:064X}", "transaction_height": 90 + index}
            for index in range(8)
        ],
        "validator_status_before": snapshots,
        "validator_status_after_transactions": snapshots,
        "validator_status_after_restart": snapshots,
        "restart_status": restart_status,
        "offline_status": offline_status,
    }


def test_release_gate_accepts_complete_g3_report(tmp_path: Path) -> None:
    report_path = tmp_path / "g3-report.json"
    report_path.write_text(json.dumps(_g3_report()), encoding="utf-8")

    result = _run_gate("--g3-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G3"]["status"] == "PASS"


def test_release_gate_keeps_partial_g3_report_incomplete(tmp_path: Path) -> None:
    report_path = tmp_path / "g3-report.json"
    report_path.write_text(json.dumps(_g3_report(restart_status="SKIPPED")), encoding="utf-8")

    result = _run_gate("--g3-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G3"]["status"] == "INCOMPLETE"


def test_release_gate_accepts_complete_g4_report(tmp_path: Path) -> None:
    report_path = tmp_path / "g4-report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "rpc_endpoints": ["https://rpc-a.example", "https://rpc-b.example"],
                "finality_evidence": {"operation_id": "op-1"},
                "ownership_evidence": {
                    "status": "OUT_OF_BAND_VERIFIED",
                    "ownership_evidence_root": "sha256:reviewed-ownership",
                },
                "checks": {
                    name: {"status": "PASS", "evidence_reference": f"{name}.json"}
                    for name in (
                        "lan_acceptance",
                        "public_p2p_acceptance",
                        "bootstrap_diversity",
                        "public_rpc_observable",
                        "tls_validated",
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--g4-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G4"]["status"] == "PASS"


def test_release_gate_keeps_structurally_valid_incomplete_g4_report_incomplete(tmp_path: Path) -> None:
    report_path = tmp_path / "g4-report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "gate_status": "INCOMPLETE",
                "rpc_endpoints": ["https://rpc-a.example", "https://rpc-b.example"],
                "finality_evidence": {"operation_id": "op-1"},
                "ownership_evidence": {"status": "OUT_OF_BAND_DECLARED"},
                "checks": {
                    name: {"status": "PASS", "evidence_reference": f"{name}.json"}
                    for name in (
                        "lan_acceptance",
                        "public_p2p_acceptance",
                        "bootstrap_diversity",
                        "public_rpc_observable",
                        "tls_validated",
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--g4-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G4"]["status"] == "INCOMPLETE"


def _write_g6_bundle(root: Path, *, index: int) -> None:
    artifact = root / "release/version.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"release":"test"}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    root_hash = evidence_root([("release/version.json", digest)])
    manifest = {
        "evidence_format_version": 1,
        "network_id": "testnet",
        "release_version": "0.1.0-test",
        "profile_id": "test-profile",
        "generated_at": "2030-01-01T00:00:00Z",
        "artifacts": [{"path": "release/version.json", "sha256": digest}],
        "evidence_root": root_hash,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(index, index + 32)))
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    attestation = {
        "attestation_version": 1,
        "operator_id": f"operator-{index}",
        "control_group_id": f"group-{index}",
        "independence_status": "OUT_OF_BAND_VERIFIED",
        "operator_public_key": "ed25519:" + public_key.hex(),
        "evidence_root": root_hash,
        "signed_at": "2030-01-01T00:00:01Z",
    }
    attestation["signature"] = "ed25519:" + private_key.sign(canonical_json_bytes(attestation)).hex()
    path = root / "attestations/operator-attestation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attestation), encoding="utf-8")


def test_release_gate_requires_distinct_verified_g6_operators(tmp_path: Path) -> None:
    first = tmp_path / "operator-a"
    second = tmp_path / "operator-b"
    _write_g6_bundle(first, index=1)
    _write_g6_bundle(second, index=2)

    result = _run_gate(
        "--g6-evidence-dir",
        str(first),
        "--g6-evidence-dir",
        str(second),
        "--allow-incomplete",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G6"]["status"] == "PASS"


def test_release_gate_g7_requires_a_passing_embedded_gate_result(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)
    gate_path = evidence_dir / "gates/release-gate-result.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "gates": {f"G{index}": "PASS" for index in range(7)},
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G7"]["status"] == "PASS"


def test_release_gate_g7_rejects_missing_embedded_gate_result(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G7"]["status"] == "FAIL"

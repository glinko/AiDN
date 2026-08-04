from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.snapshot_acceptance import run_snapshot_acceptance
from aidn_hypervisor.evidence import (
    INDEPENDENCE_REVIEW_PATH,
    canonical_json_bytes,
    evidence_root,
)

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


def test_release_gate_rejects_g3_snapshots_without_validator_identity(tmp_path: Path) -> None:
    report = _g3_report()
    report["validator_status_before"][0].pop("node_id")
    report_path = tmp_path / "g3-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _run_gate("--g3-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G3"]["status"] == "FAIL"
    assert "invalid validator snapshot" in payload["gates"]["G3"]["reason"]


def test_release_gate_rejects_duplicate_g3_transaction_hashes(tmp_path: Path) -> None:
    report = _g3_report()
    report["operations"][1]["transaction_hash"] = report["operations"][0]["transaction_hash"]
    report_path = tmp_path / "g3-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _run_gate("--g3-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G3"]["status"] == "FAIL"
    assert "duplicate transaction hashes" in payload["gates"]["G3"]["reason"]


def test_release_gate_rejects_non_string_g3_transaction_hash(tmp_path: Path) -> None:
    report = _g3_report()
    report["operations"][0]["transaction_hash"] = 123
    report_path = tmp_path / "g3-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _run_gate("--g3-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G3"]["status"] == "FAIL"
    assert "invalid transaction hash" in payload["gates"]["G3"]["reason"]


def _g5_report(tmp_path: Path) -> dict:
    fixture_path = ROOT / "tests/test_fault_recovery_evidence.py"
    spec = importlib.util.spec_from_file_location("g5_fault_recovery_fixture", fixture_path)
    assert spec is not None and spec.loader is not None
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)

    g2_path = tmp_path / "g2-source.json"
    g2_path.write_text(json.dumps(run_snapshot_acceptance()), encoding="utf-8")
    live_path = tmp_path / "live-source.json"
    live_path.write_text(json.dumps(fixture._live_report()), encoding="utf-8")
    return fixture.MODULE.verify_fault_recovery_evidence(
        g2_report_path=g2_path,
        live_report_path=live_path,
    )


def _g4_checks() -> dict[str, dict[str, str]]:
    return {
        name: {
            "status": "PASS",
            "evidence_reference": "sha256:" + str(index + 1) * 64,
        }
        for index, name in enumerate(
            (
                "lan_acceptance",
                "public_p2p_acceptance",
                "bootstrap_diversity",
                "public_rpc_observable",
                "tls_validated",
            )
        )
    }


def test_release_gate_accepts_integrity_bound_g5_report(tmp_path: Path) -> None:
    report_path = tmp_path / "g5-report.json"
    report_path.write_text(json.dumps(_g5_report(tmp_path)), encoding="utf-8")

    result = _run_gate("--g5-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G5"]["status"] == "PASS"


def test_release_gate_rejects_tampered_g5_report(tmp_path: Path) -> None:
    report = _g5_report(tmp_path)
    report["drills"]["host_reboot"]["status"] = "FAIL"
    report_path = tmp_path / "g5-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _run_gate("--g5-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G5"]["status"] == "FAIL"
    assert "G5 report hash is invalid" in payload["gates"]["G5"]["reason"]


def test_release_gate_rejects_tampered_g5_source_report(tmp_path: Path) -> None:
    report = _g5_report(tmp_path)
    live_path = Path(report["live_report"])
    live = json.loads(live_path.read_text(encoding="utf-8"))
    live["drills"]["host_reboot"]["recovery_result"]["returncode"] = 1
    live_path.write_text(json.dumps(live), encoding="utf-8")
    report["report_hash"] = _report_hash({key: value for key, value in report.items() if key != "report_hash"})
    report_path = tmp_path / "g5-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _run_gate("--g5-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G5"]["status"] == "FAIL"
    assert "G5 source evidence is invalid" in payload["gates"]["G5"]["reason"]


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
                    "ownership_evidence_root": "sha256:" + "a" * 64,
                },
                "checks": _g4_checks(),
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
                "checks": _g4_checks(),
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--g4-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G4"]["status"] == "INCOMPLETE"


def test_release_gate_rejects_credentialed_g4_rpc_endpoint(tmp_path: Path) -> None:
    report_path = tmp_path / "g4-report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "rpc_endpoints": ["https://user:secret@rpc-a.example", "https://rpc-b.example"],
                "finality_evidence": {"operation_id": "op-1"},
                "ownership_evidence": {
                    "status": "OUT_OF_BAND_VERIFIED",
                    "ownership_evidence_root": "sha256:" + "a" * 64,
                },
                "checks": _g4_checks(),
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--g4-report", str(report_path), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G4"]["status"] == "FAIL"
    assert "credential-free HTTPS" in payload["gates"]["G4"]["reason"]


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
    reviewer_key = Ed25519PrivateKey.from_private_bytes(bytes(range(101, 133)))
    reviewer_public_key = reviewer_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    review_payload = {
        "review_version": 1,
        "reviewer_id": "release-reviewer-1",
        "reviewer_public_key": "ed25519:" + reviewer_public_key.hex(),
        "review_status": "VERIFIED",
        "review_basis": "test-out-of-band-review",
        "reviewed_operator_id": f"operator-{index}",
        "reviewed_control_group_id": f"group-{index}",
        "reviewed_evidence_root": root_hash,
        "reviewed_at": "2030-01-01T00:00:02Z",
    }
    review = {
        **review_payload,
        "signature": "ed25519:" + reviewer_key.sign(canonical_json_bytes(review_payload)).hex(),
    }
    review_path = root / Path(*INDEPENDENCE_REVIEW_PATH.split("/"))
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review), encoding="utf-8")


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
        "--g6-review-key",
        "release-reviewer-1=ed25519:"
        + Ed25519PrivateKey.from_private_bytes(bytes(range(101, 133)))
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex(),
        "--allow-incomplete",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G6"]["status"] == "PASS"


def test_release_gate_rejects_reviewer_key_reused_by_operator(tmp_path: Path) -> None:
    first = tmp_path / "operator-a"
    second = tmp_path / "operator-b"
    _write_g6_bundle(first, index=1)
    _write_g6_bundle(second, index=2)
    operator_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    reviewer_public_key = operator_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    for evidence_dir in (first, second):
        review_path = evidence_dir / Path(*INDEPENDENCE_REVIEW_PATH.split("/"))
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["reviewer_public_key"] = "ed25519:" + reviewer_public_key.hex()
        payload = {key: value for key, value in review.items() if key != "signature"}
        review["signature"] = "ed25519:" + operator_key.sign(canonical_json_bytes(payload)).hex()
        review_path.write_text(json.dumps(review), encoding="utf-8")

    result = _run_gate(
        "--g6-evidence-dir",
        str(first),
        "--g6-evidence-dir",
        str(second),
        "--g6-review-key",
        "release-reviewer-1=ed25519:" + reviewer_public_key.hex(),
        "--allow-incomplete",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G6"]["status"] == "FAIL"
    assert "reviewer identity" in payload["gates"]["G6"]["reason"]


def test_release_gate_g7_requires_a_passing_embedded_gate_result(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    gate_path = evidence_dir / "gates/release-gate-result.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "PASS",
                "network_id": manifest["network_id"],
                "release": manifest["release_version"],
                "profile_id": manifest["profile_id"],
                "evidence_root": manifest["evidence_root"],
                "gates": {f"G{index}": "PASS" for index in range(8)},
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["gates"]["G7"]["status"] == "PASS"


def test_release_gate_g7_rejects_context_mismatch(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    gate_path = evidence_dir / "gates/release-gate-result.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "PASS",
                "network_id": manifest["network_id"],
                "release": "wrong-release",
                "profile_id": manifest["profile_id"],
                "evidence_root": manifest["evidence_root"],
                "gates": {f"G{index}": "PASS" for index in range(8)},
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G7"]["status"] == "FAIL"
    assert "release does not match" in payload["gates"]["G7"]["reason"]


def test_release_gate_g7_rejects_missing_control_schema_version(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    gate_path = evidence_dir / "gates/release-gate-result.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "network_id": manifest["network_id"],
                "release": manifest["release_version"],
                "profile_id": manifest["profile_id"],
                "evidence_root": manifest["evidence_root"],
                "gates": {f"G{index}": "PASS" for index in range(8)},
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G7"]["status"] == "FAIL"
    assert "schema_version" in payload["gates"]["G7"]["reason"]


def test_release_gate_g7_rejects_missing_g7_entry(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    gate_path = evidence_dir / "gates/release-gate-result.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "evidence_root": manifest["evidence_root"],
                "gates": {f"G{index}": "PASS" for index in range(7)},
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G7"]["status"] == "FAIL"
    assert "missing gates: G7" in payload["gates"]["G7"]["reason"]


def test_release_gate_g7_rejects_unbound_evidence_root(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)
    gate_path = evidence_dir / "gates/release-gate-result.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "evidence_root": "sha256:" + "0" * 64,
                "gates": {f"G{index}": "PASS" for index in range(8)},
            }
        ),
        encoding="utf-8",
    )

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G7"]["status"] == "FAIL"
    assert "evidence_root" in payload["gates"]["G7"]["reason"]


def test_release_gate_g7_rejects_missing_embedded_gate_result(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_g6_bundle(evidence_dir, index=1)

    result = _run_gate("--evidence-dir", str(evidence_dir), "--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["gates"]["G7"]["status"] == "FAIL"

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
            "finality_evidence": {"operation_id": "operation-1"},
            "ownership_evidence": {"status": ownership_status},
        },
    )
    deployment = _write(
        tmp_path / "deployment.json",
        {
            "checks": {
                "public_p2p_acceptance": True,
                "bootstrap_diversity": {"status": "PASS", "evidence_reference": "peers.json"},
                "tls_validated": True,
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
    assert all(report["checks"].values())


def test_public_network_report_passes_after_independence_review(tmp_path: Path) -> None:
    paths = _source_reports(tmp_path, ownership_status="OUT_OF_BAND_VERIFIED")

    report = MODULE.build_report(
        lan_path=paths[0], external_path=paths[1], deployment_path=paths[2]
    )

    assert report["status"] == "ok"
    assert report["gate_status"] == "PASS"

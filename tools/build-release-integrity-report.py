#!/usr/bin/env python3
"""Build package artifacts and emit signed G0 release-integrity evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging.markers import Marker, default_environment
from packaging.utils import canonicalize_name

from aidn_hypervisor.consensus.implementation_profile import verify_implementation_profile
from aidn_hypervisor.consensus.public_network import PublicMultiValidatorNetworkProfile
from aidn_hypervisor.network_profile import (
    load_network_profile,
    load_network_profile_signers,
    verify_network_profile,
)

ROOT = Path(__file__).resolve().parents[1]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", commit) else None


def _git_worktree_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and not result.stdout.strip()


def _locked_packages(lock_path: Path) -> dict[str, dict[str, Any]]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv lockfile has no package records")
    result: dict[str, dict[str, Any]] = {}
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            raise ValueError("uv lockfile contains an invalid package record")
        result[canonicalize_name(package["name"])] = package
    return result


def _marker_applies(marker: str | None) -> bool:
    if not marker:
        return True
    return Marker(marker).evaluate(default_environment())


def _selected_root_names(packages: dict[str, dict[str, Any]]) -> set[str]:
    """Return direct dependencies selected by the release environment.

    The builder runs after ``uv sync --all-extras``.  Treating every package
    record in uv.lock as installed would incorrectly require optional package
    records such as coverage's ``tomli`` extra.
    """
    roots = packages.get("aidn-hypervisor")
    if roots is None:
        return set()
    selected: set[str] = set()
    for dependency in roots.get("dependencies", []):
        if isinstance(dependency, dict) and isinstance(dependency.get("name"), str):
            if _marker_applies(dependency.get("marker")):
                selected.add(canonicalize_name(dependency["name"]))
    for dependencies in roots.get("optional-dependencies", {}).values():
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if isinstance(dependency, dict) and isinstance(dependency.get("name"), str):
                if _marker_applies(dependency.get("marker")):
                    selected.add(canonicalize_name(dependency["name"]))
    return selected


def _required_missing_packages(packages: dict[str, dict[str, Any]], installed: set[str]) -> set[str]:
    """Find missing packages reachable through selected non-optional edges."""
    pending = list(_selected_root_names(packages))
    seen: set[str] = set()
    missing: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        package = packages.get(name)
        if package is None:
            missing.add(name)
            continue
        if name not in installed:
            missing.add(name)
            continue
        for dependency in package.get("dependencies", []):
            if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str):
                continue
            if _marker_applies(dependency.get("marker")):
                pending.append(canonicalize_name(dependency["name"]))
    return missing


def _license_evidence(distribution: importlib.metadata.Distribution) -> list[str]:
    evidence: list[str] = []
    metadata = distribution.metadata
    license_expression = metadata.get("License-Expression")
    if license_expression and license_expression.strip():
        evidence.append("METADATA:License-Expression=" + license_expression.strip())
    license_name = metadata.get("License")
    if license_name and license_name.strip() and license_name.strip().lower() != "unknown":
        evidence.append("METADATA:License=" + license_name.strip())
    for classifier in metadata.get_all("Classifier", []):
        if classifier.startswith("License ::"):
            evidence.append("METADATA:" + classifier)
    for file in distribution.files or ():
        name = Path(str(file)).name.upper()
        if name.startswith(("LICENSE", "COPYING", "NOTICE")):
            evidence.append("FILE:" + str(file))
    return sorted(set(evidence))


def _scan_dependency_licenses(lock_path: Path, project_license: str) -> dict[str, Any]:
    packages_by_name = _locked_packages(lock_path)
    installed_names = {
        canonicalize_name(distribution.metadata.get("Name", ""))
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    packages: list[dict[str, Any]] = []
    missing: list[str] = []
    not_installed: list[str] = []
    required_missing = _required_missing_packages(packages_by_name, installed_names)
    for name in sorted(packages_by_name):
        package_name = packages_by_name[name]["name"]
        try:
            distribution = importlib.metadata.distribution(name)
            evidence = _license_evidence(distribution)
            version = distribution.version
        except importlib.metadata.PackageNotFoundError:
            evidence = []
            version = None
        package = {"name": package_name, "version": version, "license_evidence": evidence}
        if version is None:
            package["status"] = "NOT_INSTALLED_FOR_TARGET"
            not_installed.append(package_name)
        packages.append(package)
        if version is not None and not evidence:
            missing.append(package_name)
    missing.extend(sorted(required_missing - set(missing)))
    return {
        "status": "PASS" if not missing and project_license else "FAIL",
        "project_license": project_license,
        "packages": packages,
        "missing_license_evidence": missing,
        "not_installed_for_target": not_installed,
    }


def _load_private_key(path: Path | None) -> tuple[Ed25519PrivateKey, str]:
    if path is None:
        return Ed25519PrivateKey.generate(), "EPHEMERAL_LOCAL"
    raw = path.read_text(encoding="utf-8").strip()
    if raw.startswith("ed25519:"):
        raw = raw[8:]
    try:
        seed = bytes.fromhex(raw)
    except ValueError as error:
        raise ValueError("G0 signing key must contain a 32-byte hex seed") from error
    if len(seed) != 32:
        raise ValueError("G0 signing key must contain a 32-byte hex seed")
    return Ed25519PrivateKey.from_private_bytes(seed), "EXTERNAL_KEY"


def _artifact_records(artifact_dir: Path) -> list[dict[str, Any]]:
    artifacts = []
    for path in sorted(artifact_dir.iterdir()):
        if path.is_file() and path.suffix in {".whl", ".gz", ".zip"}:
            artifacts.append(
                {
                    "path": str(path.resolve()),
                    "sha256": _sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
    return artifacts


def _public_network_release_binding(
    *,
    profile_path: Path | None,
    trusted_signers_path: Path | None,
    required: bool,
) -> dict[str, Any] | None:
    """Return the verified public-network facts bound into a G0 release.

    The Network Profile is the source of the relative paths.  This keeps a
    release builder from accepting a hand-supplied Genesis hash that happens
    to describe another chain.  The signer registry remains an independent
    local trust input and is intentionally not copied into the release facts.
    """

    if profile_path is None and trusted_signers_path is None:
        if required:
            raise ValueError("public release requires --network-profile and --network-profile-signers")
        return None
    if profile_path is None or trusted_signers_path is None:
        raise ValueError("network profile and trusted profile signers must be supplied together")

    profile_target = profile_path.expanduser().resolve()
    signers = load_network_profile_signers(trusted_signers_path)
    verification = verify_network_profile(
        profile_target,
        trusted_profile_signers=signers,
    )
    if not verification.valid:
        raise ValueError("public network profile verification failed: " + ",".join(verification.errors))
    profile = load_network_profile(profile_target)
    if required and profile.network.environment not in {"testnet", "mainnet"}:
        raise ValueError("public release requires a testnet or mainnet Network Profile")
    public_profile_file = profile.network.public_profile_file
    if public_profile_file is None or profile.network.public_profile_sha256 is None:
        raise ValueError("public release requires the signed public network profile binding")
    try:
        public_profile = PublicMultiValidatorNetworkProfile.model_validate_json(
            (profile_target.parent / public_profile_file).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise ValueError("public release cannot load the verified public network profile") from error
    if {
        validator.genesis_hash for validator in public_profile.validator_manifests
    } != {profile.network.genesis_sha256}:
        raise ValueError("public release Genesis does not match every validator manifest")
    return {
        "network_id": profile.network.network_id,
        "chain_id": profile.network.chain_id,
        "environment": profile.network.environment,
        "protocol_version": profile.network.protocol_version,
        "consensus_binding_hash": profile.consensus_binding_hash,
        "network_profile_sha256": _sha256_file(profile_target),
        "genesis_file": profile.network.genesis_file,
        "genesis_sha256": profile.network.genesis_sha256,
        "public_profile_file": public_profile_file,
        "public_profile_sha256": profile.network.public_profile_sha256,
        "public_profile_hash": public_profile.profile_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path("profiles/aidn-mainnet-candidate-1.json"))
    parser.add_argument("--fixture-manifest", type=Path, default=Path("fixtures/manifest.json"))
    parser.add_argument("--lockfile", type=Path, default=Path("uv.lock"))
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--release-id")
    parser.add_argument("--signing-key", type=Path)
    parser.add_argument(
        "--network-profile",
        type=Path,
        help="Network Profile TOML to bind into this release manifest",
    )
    parser.add_argument(
        "--network-profile-signers",
        type=Path,
        help="independent trusted signer registry for --network-profile",
    )
    parser.add_argument(
        "--require-public-network",
        action="store_true",
        help="fail unless the release binds a verified testnet/mainnet Network Profile",
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    try:
        profile = _load_json(args.profile, "implementation profile")
        verify_implementation_profile(profile)
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject.get("project")
        if not isinstance(project, dict):
            raise ValueError("pyproject project table is missing")
        license_config = project.get("license")
        if not isinstance(license_config, dict) or not isinstance(license_config.get("file"), str):
            raise ValueError("project license file is not declared")
        license_path = ROOT / license_config["file"]
        if not license_path.is_file():
            raise ValueError("project license file is missing")
        artifact_dir = (args.artifact_dir or args.report.parent / "dist").resolve()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        build = subprocess.run(
            ["uv", "build", "--out-dir", str(artifact_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        artifacts = _artifact_records(artifact_dir)
        if build.returncode != 0:
            raise ValueError("package build failed: " + (build.stderr or build.stdout)[-2000:])
        if not any(path["path"].endswith(".whl") for path in artifacts):
            raise ValueError("package build produced no wheel")
        if not any(path["path"].endswith((".tar.gz", ".zip")) for path in artifacts):
            raise ValueError("package build produced no source archive")
        source_commit = _git_commit()
        if source_commit is None:
            raise ValueError("cannot establish source commit for provenance")
        if not _git_worktree_clean():
            raise ValueError("working tree is dirty; commit the release source before building G0 evidence")
        dependency_scan = _scan_dependency_licenses(args.lockfile, license_config["file"])
        fixture_manifest_hash = _sha256_file(args.fixture_manifest)
        network_release = _public_network_release_binding(
            profile_path=args.network_profile,
            trusted_signers_path=args.network_profile_signers,
            required=args.require_public_network,
        )
        release_payload = {
            "schema_version": 1,
            "release_id": args.release_id or source_commit,
            "source_commit": source_commit,
            "profile_id": profile["profile_id"],
            "profile_commitment": profile["profile_commitment"],
            "operation_catalog_hash": profile["operation_catalog"]["operation_catalog_hash"],
            "fixture_manifest_path": str(args.fixture_manifest.resolve()),
            "fixture_manifest_hash": fixture_manifest_hash,
            "artifacts": artifacts,
            "network_release": network_release,
        }
        signing_key, signing_mode = _load_private_key(args.signing_key)
        public_key = signing_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        release_manifest = {
            "payload": release_payload,
            "payload_hash": _sha256_bytes(_canonical_bytes(release_payload)),
            "signer_public_key": "ed25519:" + public_key.hex(),
            "signature": "ed25519:" + signing_key.sign(_canonical_bytes(release_payload)).hex(),
            "signing_mode": signing_mode,
        }
        checks = {
            "provenance_build": True,
            "package_hashes": bool(artifacts),
            "signed_release_manifest": True,
            "implementation_profile": True,
            "operation_catalog": bool(profile["operation_catalog"].get("operation_catalog_hash")),
            "fixture_manifest": bool(fixture_manifest_hash),
            "dependency_license_scan": dependency_scan["status"] == "PASS",
            "public_network_release": (
                network_release is not None if args.require_public_network else True
            ),
        }
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "profile_id": profile["profile_id"],
            "profile_commitment": profile["profile_commitment"],
            "source_commit": source_commit,
            "checks": checks,
            "dependency_license_scan": dependency_scan,
            "release_manifest": release_manifest,
        }
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        payload = {"schema_version": 1, "status": "FAIL", "error": str(error)}
    payload["report_hash"] = _sha256_bytes(_canonical_bytes(payload))
    encoded = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import base64
import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _tool():
    path = Path(__file__).parents[2] / "tools" / "public-testnet-genesis.py"
    spec = importlib.util.spec_from_file_location("public_testnet_genesis", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_genesis_uses_only_public_validator_manifests(tmp_path: Path) -> None:
    tool = _tool()
    manifests: list[Path] = []
    for index in range(4):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes_raw()
        key_file = tmp_path / f"validator-{index}-private.json"
        key_file.write_text(
            json.dumps(
                {
                    "address": tool._address(public),
                    "pub_key": {"value": base64.b64encode(public).decode()},
                },
            ),
            encoding="utf-8",
        )
        manifest = tmp_path / f"validator-{index}.json"
        assert tool.extract(
            Namespace(validator_id=f"validator-{index}", validator_key=key_file, output=manifest)
        ) == 0
        manifests.append(manifest)

    output = tmp_path / "genesis.json"
    assert tool.build(
        Namespace(
            chain_id="aidn-testnet-1",
            genesis_time="2026-09-01T12:00:00Z",
            validator_manifest=manifests,
            output=output,
        )
    ) == 0
    genesis = json.loads(output.read_text(encoding="utf-8"))
    assert genesis["chain_id"] == "aidn-testnet-1"
    assert [item["name"] for item in genesis["validators"]] == [
        "validator-0",
        "validator-1",
        "validator-2",
        "validator-3",
    ]
    assert {item["power"] for item in genesis["validators"]} == {"1"}
    assert genesis["app_state"] == {}


def test_public_genesis_refuses_an_incomplete_validator_set(tmp_path: Path) -> None:
    tool = _tool()
    manifests = []
    for index in range(3):
        path = tmp_path / f"validator-{index}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "aidn.public-validator-genesis-manifest.v1",
                    "validator_id": f"validator-{index}",
                    "consensus_address": "A" * 40,
                    "consensus_public_key": "ed25519:" + "A" * 44,
                }
            ),
            encoding="utf-8",
        )
        manifests.append(path)
    with pytest.raises(ValueError, match="at least four"):
        tool.build(
            Namespace(
                chain_id="aidn-testnet-1",
                genesis_time="2026-09-01T12:00:00Z",
                validator_manifest=manifests,
                output=tmp_path / "genesis.json",
            )
        )


def test_ceremony_install_refuses_to_replace_started_comet_state(tmp_path: Path) -> None:
    tool = _tool()
    home = tmp_path / "comet"
    (home / "config").mkdir(parents=True)
    (home / "data" / "blockstore.db").mkdir(parents=True)
    (home / "config" / "genesis.json").write_text("{}", encoding="utf-8")
    (home / "config" / "priv_validator_key.json").write_text("{}", encoding="utf-8")
    genesis = tmp_path / "genesis.json"
    genesis.write_text('{"chain_id":"aidn-testnet-1"}', encoding="utf-8")
    with pytest.raises(ValueError, match="state exists"):
        tool.install(
            Namespace(
                genesis=genesis,
                comet_home=home,
                confirm_unstarted="I_CONFIRM_NO_BLOCK_HAS_BEEN_PRODUCED",
            )
        )

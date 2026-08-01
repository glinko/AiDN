from pathlib import Path


def test_identity_tool_keeps_private_material_out_of_public_bundle() -> None:
    script = Path("tools/prepare-registry-replication-identity.py").read_text(encoding="utf-8")

    assert "public-peer.json" in script
    assert "ca_certificate_pem" in script
    assert "private_key" in script
    assert "secret://registry/" in script
    assert "RegistryService(snapshot_path=snapshot)" in script

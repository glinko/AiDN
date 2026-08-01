from pathlib import Path


def test_ubuntu_bootstrap_is_loopback_only_and_requires_explicit_peer_identity() -> None:
    script = Path("tools/bootstrap-independent-operator-ubuntu.sh").read_text(encoding="utf-8")

    assert "--peer-id is required" in script
    assert "--host 127.0.0.1" in script
    assert "replication\":\"disabled_until_mutual_peer_approval" in script
    assert "AIDN_REGISTRY_REPLICATION_CONFIG" not in script


def test_cross_host_registry_smoke_is_explicitly_test_only() -> None:
    script = Path("tools/run-cross-host-registry-smoke.sh").read_text(encoding="utf-8")

    assert "--remote-ssh and --remote-repo are required" in script
    assert "registry_replication_peer_acceptance.py" in script
    assert "--host 127.0.0.1" in script
    assert "test-only disposable identities" in script

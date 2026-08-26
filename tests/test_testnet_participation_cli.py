from __future__ import annotations

from aidn_hypervisor.operator_cli import main as operator_cli_main


def test_participation_cli_verifies_policy_and_reproduces_empty_settlement(
    tmp_path, capsys
) -> None:
    policy = "config/testnet-participation.example.toml"
    assert operator_cli_main(["participation", "--program-path", policy, "verify"]) == 0
    assert '"policy_hash":"sha256:' in capsys.readouterr().out

    assert operator_cli_main(
        [
            "participation",
            "--program-path",
            policy,
            "calculate",
            "--evidence-store",
            str(tmp_path / "evidence.sqlite"),
            "--protocol-epoch",
            "1000",
            "--source-epoch-transition-operation-id",
            "epoch-transition:1000",
            "--period-start",
            "2026-09-01T00:00:00Z",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert '"total_reward_q_atoms":0' in output
    assert '"source_epoch_transition_operation_id":"epoch-transition:1000"' in output

#!/usr/bin/env python3
"""Read-only cryptographic finality check for an external CometBFT testnet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aidn_hypervisor.consensus.external_acceptance import (
    ExternalCometBftAcceptanceConfig,
    verify_external_cometbft_acceptance,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = ExternalCometBftAcceptanceConfig.model_validate_json(
            args.config.read_text(encoding="utf-8")
        )
        result = verify_external_cometbft_acceptance(config=config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

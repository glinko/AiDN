"""Run one explicitly configured real-provider conformance profile."""

import argparse
import os
import subprocess
import sys

PROFILES = {
    "llamacpp": {
        "test": "tests/integration/test_llamacpp_live.py",
        "required": ("AIDN_LLAMACPP_ENDPOINT", "AIDN_LLAMACPP_MODEL"),
        "enable_variable": "AIDN_LLAMACPP_LIVE",
    },
    "vllm": {
        "test": "tests/integration/test_vllm_live.py",
        "required": ("AIDN_VLLM_ENDPOINT", "AIDN_VLLM_MODEL"),
    },
    "ollama": {
        "test": "tests/integration/test_ollama_live.py",
        "required": ("AIDN_OLLAMA_ENDPOINT", "AIDN_OLLAMA_MODEL"),
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one configured AiDN real-provider conformance profile."
    )
    parser.add_argument("--provider", choices=sorted(PROFILES), required=True)
    args = parser.parse_args(argv)
    profile = PROFILES[args.provider]
    environment = os.environ.copy()
    missing = [name for name in profile["required"] if not environment.get(name, "").strip()]
    if missing:
        parser.error(
            f"set {', '.join(missing)} before running the {args.provider} live profile"
        )
    if enable_variable := profile.get("enable_variable"):
        environment[enable_variable] = "1"

    print(f"Running {args.provider} live-provider conformance: {profile['test']}")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", profile["test"], "--no-cov"],
        env=environment,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

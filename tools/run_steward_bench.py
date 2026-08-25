#!/usr/bin/env python3
"""Run the bounded StewardBench locally or against a read-only chat endpoint.

Examples:

    python tools/run_steward_bench.py
    python tools/run_steward_bench.py --api-url http://127.0.0.1:8766 --include-output
    python tools/run_steward_bench.py --api-url http://127.0.0.1:8766 --json report.json

The live mode sends only the case message to the chat API.  It never sends a
tool call and never applies an operator mutation.
"""

# The script is intentionally runnable from a source checkout without an
# editable install.  Keep the path bootstrap local to this developer tool.
# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.steward_bench import (  # noqa: E402
    StewardBenchCase,
    evaluate_steward_case,
    load_steward_bench_cases,
    summarize_steward_bench,
)


CHAT_PATH = "/operators/dashboard/steward/chat"


def _chat_url(value: str) -> str:
    base = value.rstrip("/")
    return base if base.endswith(CHAT_PATH) else f"{base}{CHAT_PATH}"


def _post_chat(url: str, case: StewardBenchCase, timeout: float) -> tuple[str | None, dict, str | None, float]:
    payload = json.dumps(
        {
            "message": case.message,
            "parameters": {"diagnostic_snapshot": case.context},
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied endpoint
            body = json.loads(response.read().decode("utf-8"))
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not isinstance(body, dict):
            return None, {}, "chat endpoint returned a non-object response", elapsed_ms
        output_text = str(body.get("output_text") or "")
        decision = body.get("decision")
        if isinstance(decision, dict):
            output_text = f"{output_text}\n{json.dumps(decision, ensure_ascii=False)}"
        usage = dict(body.get("usage") or {})
        usage["response_mode"] = str(body.get("response_mode") or "model_augmented")
        return output_text, usage, None, elapsed_ms
    except HTTPError as error:
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            detail = error.read().decode("utf-8")[:1024]
        except OSError:
            detail = ""
        suffix = f": {detail}" if detail else ""
        return None, {}, f"HTTPError: {error}{suffix}", elapsed_ms
    except (URLError, TimeoutError, OSError, ValueError) as error:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return None, {}, f"{type(error).__name__}: {error}", elapsed_ms


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", help="optional Hypervisor base URL for live read-only chat")
    parser.add_argument("--fixture", type=Path, help="StewardBench JSON fixture")
    parser.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    parser.add_argument("--timeout", type=float, default=120.0, help="per-request timeout in seconds")
    parser.add_argument("--json", dest="json_path", type=Path, help="write the machine-readable report")
    parser.add_argument("--include-output", action="store_true", help="print redacted response previews")
    return parser.parse_args()


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="backslashreplace")
    args = _parse_args()
    cases = load_steward_bench_cases(args.fixture)
    if args.limit:
        if args.limit < 1:
            raise SystemExit("--limit must be positive")
        cases = cases[: args.limit]

    live_url = _chat_url(args.api_url) if args.api_url else None
    results = []
    errors: dict[str, str] = {}
    for index, case in enumerate(cases, start=1):
        output = None
        usage = {}
        latency_ms = None
        error = None
        if live_url:
            output, usage, error, latency_ms = _post_chat(live_url, case, args.timeout)
            if error:
                errors[case.id] = error
        result = evaluate_steward_case(
            case,
            output_text=output,
            latency_ms=latency_ms,
            usage=usage,
        )
        results.append(result)
        line = (
            f"[{index:02d}/{len(cases):02d}] {case.id:<30} "
            f"guard={'PASS' if result.guard_passed else 'FAIL'} "
            f"case={'PASS' if result.passed else 'REVIEW'}"
        )
        if latency_ms is not None:
            line += f" {latency_ms / 1000:.1f}s"
        response_mode = usage.get("response_mode")
        if response_mode:
            line += f" mode={response_mode}"
        if args.include_output and result.response_preview:
            line += f" | {result.response_preview.replace(chr(10), ' ')[:180]}"
        if error:
            line += f" | ERROR: {error}"
        print(line)

    report = {
        "mode": "live" if live_url else "deterministic_guard_only",
        "api_url": live_url,
        "summary": summarize_steward_bench(results),
        "errors": errors,
        "cases": [result.as_payload() for result in results],
    }
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"report written to {args.json_path}")
    return 0 if not errors and all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

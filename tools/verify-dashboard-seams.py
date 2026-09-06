#!/usr/bin/env python3
"""Verify the operator dashboard composition-root seams introduced in M0.4."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPOSITORY_ROOT / "web" / "operator-dashboard" / "src"
SHELL_ROOT = APP_ROOT / "app"

REQUIRED_FILES = (
    APP_ROOT / "App.tsx",
    SHELL_ROOT / "classic-dashboard.tsx",
    SHELL_ROOT / "dashboard-routing.ts",
    SHELL_ROOT / "HypervisorSelector.tsx",
    SHELL_ROOT / "Navigation.tsx",
    SHELL_ROOT / "notification-context.tsx",
    SHELL_ROOT / "OperationNotice.tsx",
    SHELL_ROOT / "operator-providers.tsx",
    SHELL_ROOT / "screen-registry.ts",
    SHELL_ROOT / "shell-types.ts",
    SHELL_ROOT / "TopBar.tsx",
)
IMPORT_RE = re.compile(r"from\s+['\"](@/app/[^'\"]+)['\"]")


def fail(message: str) -> None:
    print(f"Dashboard seam verification failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_import(specifier: str) -> Path | None:
    candidate = APP_ROOT.parent / specifier.removeprefix("@/")
    for suffix in ("", ".ts", ".tsx"):
        path = candidate.with_suffix(suffix) if suffix else candidate
        if path.is_file():
            return path
    for index_name in ("index.ts", "index.tsx"):
        path = candidate / index_name
        if path.is_file():
            return path
    return None


def assert_no_app_cycles() -> None:
    graph: dict[Path, set[Path]] = {}
    for source in SHELL_ROOT.glob("*.ts*"):
        dependencies: set[Path] = set()
        for specifier in IMPORT_RE.findall(source.read_text(encoding="utf-8")):
            target = resolve_import(specifier)
            if target and target.parent == SHELL_ROOT:
                dependencies.add(target)
        graph[source] = dependencies

    visiting: set[Path] = set()
    visited: set[Path] = set()

    def visit(source: Path) -> None:
        if source in visiting:
            fail(f"circular shell import through {source.relative_to(REPOSITORY_ROOT)}")
        if source in visited:
            return
        visiting.add(source)
        for dependency in graph.get(source, set()):
            visit(dependency)
        visiting.remove(source)
        visited.add(source)

    for source in graph:
        visit(source)


def main() -> int:
    for path in REQUIRED_FILES:
        if not path.is_file():
            fail(f"missing {path.relative_to(REPOSITORY_ROOT)}")

    composition_root = (APP_ROOT / "App.tsx").read_text(encoding="utf-8")
    if "from '@/app/classic-dashboard'" not in composition_root:
        fail("App.tsx must delegate to the Classic dashboard implementation")
    if "QueryClient" in composition_root or "useDashboardData" in composition_root:
        fail("App.tsx must not own providers or dashboard queries")
    if composition_root.count("function App") != 1:
        fail("App.tsx must expose one composition function")

    routing = (SHELL_ROOT / "dashboard-routing.ts").read_text(encoding="utf-8")
    for symbol in ("dashboardScreenFromHash", "navigateToDashboardScreen", "useDashboardRouting"):
        if symbol not in routing:
            fail(f"routing seam is missing {symbol}")

    registry = (SHELL_ROOT / "screen-registry.ts").read_text(encoding="utf-8")
    for symbol in ("navigationItems", "advancedItems", "isOperationsScreen"):
        if symbol not in registry:
            fail(f"screen registry is missing {symbol}")

    providers = (SHELL_ROOT / "operator-providers.tsx").read_text(encoding="utf-8")
    if "QueryClientProvider" not in providers or "TooltipProvider" not in providers:
        fail("provider seam must own QueryClientProvider and TooltipProvider")

    notices = (SHELL_ROOT / "notification-context.tsx").read_text(encoding="utf-8")
    if "NotificationContext" not in notices or "useNotificationSink" not in notices:
        fail("notice seam must expose NotificationContext and useNotificationSink")

    operation_notice = (SHELL_ROOT / "OperationNotice.tsx").read_text(encoding="utf-8")
    if "useNotificationSink" not in operation_notice or "OperationNotice" not in operation_notice:
        fail("operation notice seam must forward mutation messages to the shell sink")

    assert_no_app_cycles()
    print(f"Verified dashboard composition root and {len(REQUIRED_FILES) - 1} shell seams; no shell import cycles found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

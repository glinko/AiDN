"""Reusable RFC-0054 conformance assertions for Runtime Adapter profiles."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aidn_hypervisor.runtime_protocol.service import RuntimeProtocolError


@dataclass(frozen=True)
class RuntimeConformanceCase:
    case_id: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RuntimeConformanceReport:
    cases: tuple[RuntimeConformanceCase, ...]

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)


class RuntimeProtocolConformanceHarness:
    """Run Adapter protocol checks while retaining a compact audit report."""

    def __init__(self) -> None:
        self._cases: list[RuntimeConformanceCase] = []

    def assert_success(self, case_id: str, operation: Callable[[], Any]) -> Any:
        try:
            value = operation()
        except Exception as exc:
            self._record(case_id, False, f"unexpected {type(exc).__name__}: {exc}")
            raise AssertionError(f"{case_id}: operation failed") from exc
        self._record(case_id, True, "accepted")
        return value

    def assert_protocol_error(
        self,
        case_id: str,
        operation: Callable[[], Any],
        expected_code: str,
    ) -> RuntimeProtocolError:
        try:
            operation()
        except RuntimeProtocolError as exc:
            if exc.code == expected_code:
                self._record(case_id, True, f"rejected with {expected_code}")
                return exc
            self._record(case_id, False, f"expected {expected_code}, got {exc.code}")
            raise AssertionError(f"{case_id}: unexpected Runtime Protocol error {exc.code}") from exc
        except Exception as exc:
            self._record(case_id, False, f"unexpected {type(exc).__name__}: {exc}")
            raise AssertionError(f"{case_id}: unexpected error") from exc
        self._record(case_id, False, f"expected {expected_code}, operation succeeded")
        raise AssertionError(f"{case_id}: expected Runtime Protocol error {expected_code}")

    def assert_transport_failure(
        self,
        case_id: str,
        operation: Callable[[], Any],
        expected_exception: type[Exception] | tuple[type[Exception], ...] = ConnectionError,
    ) -> Exception:
        """Record an expected transport failure after an attempted protocol operation."""
        try:
            operation()
        except expected_exception as exc:
            self._record(case_id, True, f"transport failed with {type(exc).__name__}")
            return exc
        except Exception as exc:
            self._record(case_id, False, f"unexpected {type(exc).__name__}: {exc}")
            raise AssertionError(f"{case_id}: unexpected error") from exc
        self._record(case_id, False, "expected transport failure, operation succeeded")
        raise AssertionError(f"{case_id}: expected transport failure")

    def assert_idempotent(
        self,
        case_id: str,
        operation: Callable[[], Any],
        identity: Callable[[Any], object] = lambda value: value,
    ) -> Any:
        first = self.assert_success(f"{case_id}.initial", operation)
        second = self.assert_success(f"{case_id}.redelivery", operation)
        if identity(first) != identity(second):
            self._record(case_id, False, "redelivery changed semantic identity")
            raise AssertionError(f"{case_id}: redelivery is not idempotent")
        self._record(case_id, True, "redelivery preserved semantic identity")
        return first

    def report(self) -> RuntimeConformanceReport:
        return RuntimeConformanceReport(cases=tuple(self._cases))

    def _record(self, case_id: str, passed: bool, detail: str) -> None:
        self._cases.append(
            RuntimeConformanceCase(case_id=case_id, passed=passed, detail=detail)
        )

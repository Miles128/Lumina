"""Offline eval harness for Lumina agent runtime (PRD F23)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent / "cases"


@dataclass(frozen=True)
class EvalCase:
    id: str
    kind: str
    payload: dict[str, Any]


def load_cases(cases_dir: Path | None = None) -> list[EvalCase]:
    root = cases_dir or CASES_DIR
    cases: list[EvalCase] = []
    if not root.exists():
        return cases
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append(
            EvalCase(
                id=str(data.get("id") or path.stem),
                kind=str(data["kind"]),
                payload=data,
            )
        )
    return cases


EvalHandler = Callable[[EvalCase], None]

_HANDLERS: dict[str, EvalHandler] = {}


def register_handler(kind: str) -> Callable[[EvalHandler], EvalHandler]:
    def decorator(fn: EvalHandler) -> EvalHandler:
        _HANDLERS[kind] = fn
        return fn

    return decorator


def run_case(case: EvalCase) -> None:
    handler = _HANDLERS.get(case.kind)
    if handler is None:
        raise AssertionError(f"no eval handler for kind={case.kind!r} (case={case.id})")
    handler(case)


def run_all(cases_dir: Path | None = None) -> list[str]:
    """Run all cases; return list of case ids that passed."""
    # Import handlers for side-effect registration.
    from . import handlers as _handlers  # noqa: F401

    passed: list[str] = []
    for case in load_cases(cases_dir):
        run_case(case)
        passed.append(case.id)
    return passed

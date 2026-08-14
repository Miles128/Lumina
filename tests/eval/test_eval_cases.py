"""Run offline eval cases (F23)."""

from __future__ import annotations

from pathlib import Path

import pytest

from . import handlers as _handlers  # noqa: F401
from .harness import load_cases, run_case


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c.id)
def test_eval_case(case, tmp_path: Path) -> None:
    run_case(case)

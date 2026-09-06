"""Statically bans PEP 604 `X | Y` union syntax anywhere in app/.

This isn't a style preference: `from __future__ import annotations` only
defers *annotation* evaluation, not plain expressions -- a module-level type
alias like `PositionKey = tuple[str, str | None]` still executes `str | None`
immediately at import time regardless of that future import. Separately,
FastAPI explicitly re-evaluates route/Depends() parameter annotations at
registration time, which defeats the future-import deferral for those too.
Both have caused real import-time crashes on this app's actual deployment
target (Python 3.9, where `X | Y` only works from 3.10 on) -- and our own
test suite runs on Python 3.11, which tolerates this syntax at runtime and
so can never catch it. A blanket static ban is simpler and safer than
classifying which specific usages are actually dangerous.

Use typing.Optional[X] / typing.Union[X, Y] instead, everywhere in app/.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _bitor_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return sorted(
        node.lineno for node in ast.walk(tree) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
    )


@pytest.mark.parametrize("path", sorted(APP_DIR.rglob("*.py")), ids=lambda p: str(p.relative_to(APP_DIR)))
def test_no_pep604_union_syntax(path: Path):
    bad_lines = _bitor_lines(path)
    assert not bad_lines, (
        f"{path.relative_to(APP_DIR)} uses `X | Y` union syntax on line(s) {bad_lines} -- "
        "use typing.Optional[X] / typing.Union[X, Y] instead (Python 3.9 deployment target)."
    )

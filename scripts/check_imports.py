#!/usr/bin/env python3
"""
Verify that ``src/logiq/`` imports only stdlib.

The core package has zero third-party runtime dependencies
(docs/system-design.md §3). This script enforces that structurally by
AST-walking every .py file under ``src/logiq/`` and asserting every
top-level import belongs to one of:

  - the Python standard library (``sys.stdlib_module_names``)
  - a ``logiq.*`` submodule (internal)
  - a ``logix_*`` sibling package (logiq_pydantic, logiq_ai, logiq_mcp —
    optional extras, always imported behind ``try/except ImportError``)

Any other import fails the check. Exit 0 on pass, 1 on any violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "logiq"
SIBLINGS = frozenset({"logiq_pydantic", "logiq_ai", "logiq_mcp"})


def _top_level_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name.split(".")[0]))
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue  # relative import of a logiq submodule
            if node.module:
                found.append((node.lineno, node.module.split(".")[0]))
    return found


def main() -> int:
    if not SRC.exists():
        print(f"FAIL: source directory not found: {SRC}", file=sys.stderr)
        return 1

    stdlib = set(sys.stdlib_module_names)
    offenders: list[str] = []
    files = sorted(SRC.rglob("*.py"))

    for path in files:
        for lineno, mod in _top_level_imports(path):
            if mod in stdlib or mod == "logiq" or mod in SIBLINGS:
                continue
            offenders.append(
                f"  {path.relative_to(ROOT)}:{lineno}: non-stdlib import {mod!r}"
            )

    if offenders:
        print(
            "FAIL: src/logiq/ imports non-stdlib modules:",
            file=sys.stderr,
        )
        for line in offenders:
            print(line, file=sys.stderr)
        print(
            "\nThe core must have zero third-party runtime deps "
            "(docs/system-design.md §3).",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(files)} files under src/logiq/ import only stdlib.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
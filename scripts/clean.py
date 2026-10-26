#!/usr/bin/env python3
"""
Remove build artifacts and caches.

Removes:

  - dist/  build/
  - *.egg-info/ (root and src/)
  - __pycache__/ (anywhere)
  - .pytest_cache/  .ruff_cache/  .mypy_cache/  .hypothesis/
  - htmlcov/  .coverage  coverage.xml

Idempotent: safe to run anytime. Does not touch installed packages in
site-packages — use ``pip uninstall logiq`` for that.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_DIRS = [
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".hypothesis",
    "htmlcov",
]
_FILES = [
    ".coverage",
    "coverage.xml",
]


def main() -> int:
    removed = 0

    for rel in _DIRS:
        target = ROOT / rel
        if target.exists():
            shutil.rmtree(target)
            print(f"removed {rel}/")
            removed += 1

    for rel in _FILES:
        target = ROOT / rel
        if target.exists():
            target.unlink()
            print(f"removed {rel}")
            removed += 1

    # egg-info anywhere
    for target in ROOT.glob("**/*.egg-info"):
        if ".venv" in target.parts or "site-packages" in target.parts:
            continue
        shutil.rmtree(target)
        print(f"removed {target.relative_to(ROOT)}/")
        removed += 1

    # __pycache__ anywhere under src/, tests/, scripts/
    for base in ("src", "tests", "scripts", "examples"):
        base_path = ROOT / base
        if not base_path.exists():
            continue
        for target in base_path.rglob("__pycache__"):
            shutil.rmtree(target, ignore_errors=True)
            removed += 1

    print(f"clean: {removed} items removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

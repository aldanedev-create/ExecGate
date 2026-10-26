# scripts/fix_rename_misses.py
"""
Patch remaining ``logix`` references after the package rename.

Targets the misses the aggressive-src-only rule cannot reach: path
literals in scripts/ and specific lines in pyproject.toml.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FIXES: dict[str, list[tuple[str, str]]] = {
    "pyproject.toml": [
        ('all = ["logix[pydantic,ai,dev]"]',
         'all = ["logiq[pydantic,ai,dev]"]'),
        ('addopts = "-ra --strict-markers --strict-config"',
         'addopts = "-ra --strict-markers --strict-config -p no:qt"'),
    ],
    "scripts/check_imports.py": [
        ('ROOT / "src" / "logix"',       'ROOT / "src" / "logiq"'),
        ('mod == "logix"',               'mod == "logiq"'),
        ('"FAIL: src/logix/ imports',    '"FAIL: src/logiq/ imports'),
        ('files under src/logix/',       'files under src/logiq/'),
        ('relative import of a logix',   'relative import of a logiq'),
        ('a ``logix.*`` submodule',      'a ``logiq.*`` submodule'),
        ('``src/logix/``',               '``src/logiq/``'),
    ],
    "scripts/release.py": [
        ('ROOT / "src" / "logix"',       'ROOT / "src" / "logiq"'),
        ('Update src/logix/__init__.py', 'Update src/logiq/__init__.py'),
    ],
    "scripts/clean.py": [
        ('pip uninstall logix',          'pip uninstall logiq'),
    ],
    "scripts/README.md": [
        ('`src/logix/`',                 '`src/logiq/`'),
        ('simple/ logix',                'simple/ logiq'),
    ],
    "README.md": [
        ('| `logix` | Core:',            '| `logiq` | Core:'),
        ('**Core (`src/logix/`)**',      '**Core (`src/logiq/`)**'),
    ],
}


def main() -> int:
    total = 0
    for relpath, edits in FIXES.items():
        path = ROOT / relpath
        if not path.exists():
            print(f"skip (missing): {relpath}")
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        applied = 0
        for old, new in edits:
            if old in text:
                text = text.replace(old, new)
                applied += 1
        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"fixed: {relpath}  ({applied}/{len(edits)} edits)")
            total += applied
        else:
            print(f"no change: {relpath}")

    print(f"\n{total} edits applied across {len(FIXES)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
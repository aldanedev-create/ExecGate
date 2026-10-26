#!/usr/bin/env python3
"""
Comprehensive post-rename fixer for the logix → logiq transition.

Scans every text file in the repo, applies fixes for any reference to the
old package name that would break functionality, and reports the ones
that need human judgment.

Three categories of remaining occurrences after the run:

  [CRITICAL]   a breaking reference our rules didn't catch (bug in rules)
  [REVIEW]     a decision needed (URLs, prose table cells, repo rename)
  [PRESERVED]  variable name, product name — expected, no action

Fixes applied:

  - Path literals:      "src/logix"            → "src/logiq"
                        ROOT / "src" / "logix" → ROOT / "src" / "logiq"
  - Module imports:     from logix             → from execgate
                        import logix           → import execgate
  - Module strings:     "logix.engine"         → "execgate.engine"
  - Package-with-extras:"logix[all]"           → "logiq[all]"
  - pyproject name:     name = "logix"         → name = "logiq"
  - pytest addopts:     add -p no:qt (fixes pytest-qt import error)
  - Deep-fix for files that had bare `import logix` in code strings:
    inside those files, `logix.X` → `execgate.X` (so code samples don't break)

Usage:

    python scripts/fix_all_logix_rename.py --dry-run   # preview only
    python scripts/fix_all_logix_rename.py             # apply
    python scripts/fix_all_logix_rename.py --check     # CI: exit 1 if issues

Exit codes:
    0 — all critical issues fixed or none found
    1 — critical issues remain (needs manual attention)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Scanning configuration
# ---------------------------------------------------------------------------

SCAN_EXTENSIONS = frozenset(
    {
        ".py",
        ".md",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".cfg",
        ".ini",
        ".txt",
        ".rst",
        ".sh",
        ".ps1",
    }
)

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".hypothesis",
        "htmlcov",
        "dist",
        "build",
        ".venv",
        "venv",
        "site-packages",
        "node_modules",
        ".idea",
        ".vscode",
    }
)

# Skip these — one-time rename tools; don't self-modify
SKIP_FILES = frozenset(
    {
        "scripts/rename_to_logiq.py",
        "scripts/fix_rename_misses.py",
        "scripts/fix_all_logix_rename.py",
    }
)


# ---------------------------------------------------------------------------
# Fix rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixRule:
    pattern: re.Pattern[str]
    replacement: str
    category: str
    description: str


PATH_RULES = [
    FixRule(
        re.compile(r"""(['"])src/logix(['/])"""),
        r"\1src/logiq\2",
        "path",
        'filesystem path "src/logix" → "src/logiq"',
    ),
    FixRule(
        re.compile(r"""(['"])src/logix(['"])"""),
        r"\1src/logiq\2",
        "path",
        'filesystem path "src/logix" → "src/logiq"',
    ),
    FixRule(
        re.compile(r'ROOT\s*/\s*"src"\s*/\s*"logix"'),
        'ROOT / "src" / "logiq"',
        "path",
        'ROOT / "src" / "logix" → ROOT / "src" / "logiq"',
    ),
    FixRule(
        re.compile(r"(?<![\w/])src/logix(?:/|(?=[\s`'\"),\n]))"),
        "src/logiq",
        "path",
        "src/logix/ in prose or docstrings → src/logiq/",
    ),
]

MODULE_RULES = [
    FixRule(
        re.compile(r"\bfrom logix(?=[\s.])"),
        "from execgate",
        "module",
        "from logix → from execgate",
    ),
    FixRule(
        re.compile(r"\bimport logix(?=[\s.,]|$)"),
        "import execgate",
        "module",
        "import logix → import execgate",
    ),
    FixRule(
        # "logix.X" in a quoted string, but NOT "logix.py" (file paths)
        re.compile(r"""(['"])logix\.(?!py\b)"""),
        r"\1logiq.",
        "module",
        'string "logix.X" → "execgate.X"',
    ),
]

PIP_RULES = [
    FixRule(
        re.compile(r"""(['"\[]\s*)logix\["""),
        r"\1logiq[",
        "pip",
        '"logix[extra]" → "logiq[extra]"',
    ),
]

PYPROJECT_RULES = [
    FixRule(
        re.compile(r'^name = "logix"$', re.MULTILINE),
        'name = "logiq"',
        "pyproject",
        'pyproject name = "logix" → "logiq"',
    ),
]

PYTEST_RULES = [
    FixRule(
        re.compile(
            r'^addopts = "(-ra --strict-markers --strict-config)(?! -p no:qt)"',
            re.MULTILINE,
        ),
        r'addopts = "\1 -p no:qt"',
        "pytest",
        "add -p no:qt to pytest addopts (avoids pytest-qt import error)",
    ),
]

ALL_RULES: list[FixRule] = PATH_RULES + MODULE_RULES + PIP_RULES + PYPROJECT_RULES + PYTEST_RULES


# ---------------------------------------------------------------------------
# File selection
# ---------------------------------------------------------------------------


def should_scan(path: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return False
    if path.suffix not in SCAN_EXTENSIONS:
        return False
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        return False
    return rel not in SKIP_FILES


def scan_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and should_scan(p))


# ---------------------------------------------------------------------------
# Rule application
# ---------------------------------------------------------------------------


def apply_rules(text: str) -> tuple[str, list[str]]:
    """Apply all FixRules. Return (new_text, descriptions_of_matches)."""
    applied: list[str] = []
    for rule in ALL_RULES:
        new_text, n = rule.pattern.subn(rule.replacement, text)
        if n:
            applied.extend([rule.description] * n)
        text = new_text
    return text, applied


def has_bare_import(text: str) -> bool:
    """True if ``text`` contains ``import logix`` (bare, not ``from``)."""
    return bool(
        re.search(
            r"^\s*import logix(?:$|\s*[,;]|\s+as\b)",
            text,
            re.MULTILINE,
        )
    )


def deep_fix_bare_imports(text: str) -> tuple[str, int]:
    """
    In a file that had ``import logix`` (in code or a code string), rename
    ``logix.X`` → ``execgate.X`` so code samples that use the imported
    module stay correct. Preserves lines that assign or bind ``logix`` as
    a variable.
    """
    lines = text.split("\n")
    new_lines: list[str] = []
    changed = 0
    for line in lines:
        stripped = line.lstrip()

        # Preserve variable definitions/bindings
        is_binding = (re.match(r"logix\s*=", stripped) and "==" not in stripped) or re.match(
            r"(?:for|with|as)\s+logix\b", stripped
        )
        if is_binding:
            new_lines.append(line)
            continue

        new_line = re.sub(r"\blogix(?=\.)", "logiq", line)
        if new_line != line:
            changed += 1
        new_lines.append(new_line)

    return "\n".join(new_lines), changed


# ---------------------------------------------------------------------------
# Remaining-occurrence categorization
# ---------------------------------------------------------------------------

# Lines matching these, after all fixes, are CRITICAL (rules should have caught).
_CRITICAL_RES = [
    re.compile(r"""(['"])src/logix"""),
    re.compile(r"\bfrom logix(?=[\s.])"),
    re.compile(r"""(['"])logix\.[a-zA-Z]"""),  # "logix.engine" etc.
    re.compile(r"""(['"\[]\s*)logix\["""),  # "logix[all]"
    re.compile(r'^name = "logix"', re.MULTILINE),
    re.compile(r"\bimport logix(?=[\s.,]|$)"),
]

# Lines matching these are PRESERVED (expected, do not flag).
_PRESERVED_RES = [
    # Variable assignment
    re.compile(r"^\s*logix\s*="),
    # Decorator / method on variable
    re.compile(r"^\s*@logix\.\w+"),
    re.compile(
        r"\blogix\.(run|verify|execute|capability|registry|tools|schemas|authorize|require_approval|grounding|policy|context|limits|audit|explain|dry_run)\b"
    ),
    # Class name (capital L)
    re.compile(r"\bLogix\b"),
    # Prose: "Logix" the product, "the logix library"
    re.compile(r"\bLogix\b"),
    # bindings
    re.compile(r"(?:for|with|as)\s+logix\b"),
]


def categorize_line(line: str, *, file_path: Path) -> str:
    """Return 'CRITICAL', 'PRESERVED', or 'REVIEW' for a line containing 'logix'."""
    for rx in _CRITICAL_RES:
        if rx.search(line):
            return "CRITICAL"
    for rx in _PRESERVED_RES:
        if rx.search(line):
            return "PRESERVED"

    # URL / repo path → REVIEW (cosmetic — repo rename decision)
    if re.search(r"(github\.com|pypi\.org|readthedocs\.io)/[\w\-./]*logix", line):
        return "REVIEW"

    # Bare `` `logix` `` in markdown table cell → REVIEW
    if "|" in line and re.search(r"\|\s*`?logix`?\s*\|", line):
        return "REVIEW"

    # Anything else containing lowercase "logix" → REVIEW (likely prose)
    return "REVIEW"


def remaining_occurrences(path: Path) -> list[tuple[int, str, str]]:
    """Return [(lineno, line_stripped, category)] for lines with 'logix'."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    out: list[tuple[int, str, str]] = []
    pattern = re.compile(r"\blogix\b", re.IGNORECASE)
    for lineno, line in enumerate(text.splitlines(), 1):
        if not pattern.search(line):
            continue
        category = categorize_line(line, file_path=path)
        out.append((lineno, line.strip(), category))
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would change; do not modify files"
    )
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 if any CRITICAL reference remains"
    )
    args = parser.parse_args(argv)

    files = scan_files()
    print(f"Scanning {len(files)} files under {ROOT}\n")

    # ---- Phase 1: apply rules ------------------------------------------
    print("=== Applying fixes ===")
    fixed_total = 0
    files_changed = 0
    per_file: list[tuple[Path, list[str]]] = []

    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        had_bare = has_bare_import(original)
        new_text, applied = apply_rules(original)

        if had_bare:
            new_text, n_deep = deep_fix_bare_imports(new_text)
            if n_deep:
                applied.append(f"deep fix: {n_deep} logix.X → execgate.X")

        if new_text != original:
            fixed_total += len(applied)
            files_changed += 1
            per_file.append((path, applied))
            if not args.dry_run:
                path.write_text(new_text, encoding="utf-8")

    for path, applied in per_file:
        rel = path.relative_to(ROOT)
        print(f"  {rel}")
        for desc in applied:
            print(f"    - {desc}")

    print(f"\n{files_changed} files changed, {fixed_total} fixes applied.")
    if args.dry_run:
        print("(dry-run — no files were modified)")

    # ---- Phase 2: report remaining -------------------------------------
    print("\n=== Remaining occurrences ===")
    by_category: dict[str, list[tuple[Path, int, str]]] = {
        "CRITICAL": [],
        "REVIEW": [],
        "PRESERVED": [],
    }

    for path in files:
        for lineno, line, cat in remaining_occurrences(path):
            by_category[cat].append((path, lineno, line))

    for cat in ("CRITICAL", "REVIEW", "PRESERVED"):
        entries = by_category[cat]
        if not entries:
            print(f"\n[{cat}] — none")
            continue
        print(f"\n[{cat}] — {len(entries)} occurrences")
        # Truncate snippets for readability
        for path, lineno, line in entries[:40]:
            rel = path.relative_to(ROOT)
            snippet = line if len(line) <= 100 else line[:97] + "..."
            print(f"  {rel}:{lineno}: {snippet}")
        if len(entries) > 40:
            print(f"  ... and {len(entries) - 40} more")

    # ---- Phase 3: verdict ----------------------------------------------
    print("\n=== Verdict ===")
    critical = len(by_category["CRITICAL"])
    review = len(by_category["REVIEW"])
    preserved = len(by_category["PRESERVED"])

    if critical:
        print(f"CRITICAL: {critical} breaking references remain.")
        print("  These should have been caught by the rules — fix manually.")
    else:
        print("No critical references remain.")

    if review:
        print(f"REVIEW: {review} items need human judgment")
        print("  (GitHub URLs, prose tables, repo rename decisions).")

    if preserved:
        print(f"PRESERVED: {preserved} items — variable names, class names,")
        print("  product references. These are correct as-is.")

    # ---- Phase 4: next steps -------------------------------------------
    if not args.dry_run:
        print("\n=== Next steps ===")
        print("  pip uninstall -y logix logiq")
        print('  pip install -e ".[dev]"')
        print('  python -c "from execgate import Logix; print(Logix)"')
        print("  pytest -p no:qt")

    if args.check and critical:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

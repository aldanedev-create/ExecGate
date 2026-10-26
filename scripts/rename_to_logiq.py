#!/usr/bin/env python3
"""
Rename the Logix package to Logiq.

Renames:
  src/logix/          -> src/logiq/
  src/logiq_pydantic/ -> src/logiq_pydantic/
  src/logiq_ai/       -> src/logiq_ai/
  src/logiq_mcp/      -> src/logiq_mcp/

Rewrites imports and module references across:
  src/, tests/, scripts/, examples/, docs/, pyproject.toml,
  README.md, CHANGELOG.md, CONTRIBUTING.md

Preserves:
  - The class name ``Logix`` (capital L) — the brand survives in user code.
  - Local variables named ``logix`` in tests, examples, and user-facing
    code. ``from logiq import Logix; logix = Logix()`` still works.
  - Prose references to "Logix" the product.
  - URLs (e.g. github.com/logix-dev/logix). Repo rename is a separate
    decision.

What it does NOT do:
  - Rename your local git repo (GitHub org/repo name).
  - Rename the ``Logix`` class, ``LogixMCPServer``, ``LogixMCPProxy``, etc.
  - Rewrite git history. Expect ``git diff`` to show renames + edits.
  - Modify prose in docs that references "logix" as a package identifier
    in freestanding text. Review the "Remaining" report at the end.

Usage:
    python scripts/rename_to_logiq.py --dry-run
    python scripts/rename_to_logiq.py
    python scripts/rename_to_logiq.py --skip-verify  # skip pytest
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Renames
# ---------------------------------------------------------------------------

DIR_RENAMES = [
    ("src/logix", "src/logiq"),
    ("src/logiq_pydantic", "src/logiq_pydantic"),
    ("src/logiq_ai", "src/logiq_ai"),
    ("src/logiq_mcp", "src/logiq_mcp"),
]

# Conservative, safe replacements — applied to all files.
IMPORT_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # Package name with underscore — most specific first
    (re.compile(r"\blogix_pydantic\b"), "logiq_pydantic"),
    (re.compile(r"\blogix_ai\b"), "logiq_ai"),
    (re.compile(r"\blogix_mcp\b"), "logiq_mcp"),
    # Import statements (matches ``from logiq import`` and ``from logiq.xxx``)
    (re.compile(r"\bfrom logix\b"), "from logiq"),
    (re.compile(r"\bimport logix\b"), "import logiq"),
    # pip install commands
    (re.compile(r"\bpip install logix\b"), "pip install logiq"),
    (re.compile(r"""(pip install ["'])logix(\[)"""), r"\1logiq\2"),
    (re.compile(r"""(")logix\[(pydantic|ai|mcp|all|dev)\]"""), r"\1logiq[\2]"),
    (re.compile(r"""(')logix\[(pydantic|ai|mcp|all|dev)\]"""), r"\1logiq[\2]"),
]

# Aggressive, applied ONLY to files under src/ — inside the package,
# any lowercase ``logix`` refers to the package itself. Variable names
# like ``logix = Logix()`` do not appear in src/.
SRC_AGGRESSIVE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\blogix\b"), "logiq"),
]

# pyproject.toml specific patterns
PYPROJECT_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'^name = "logix"$', re.MULTILINE), 'name = "logiq"'),
    (re.compile(r'"src/logix"'), '"src/logiq"'),
    (re.compile(r'"src/logiq_pydantic"'), '"src/logiq_pydantic"'),
    (re.compile(r'"src/logiq_ai"'), '"src/logiq_ai"'),
    (re.compile(r'"src/logiq_mcp"'), '"src/logiq_mcp"'),
    (
        re.compile(r'^Homepage = "https://github\.com/[^/]+/logix"$', re.MULTILINE),
        lambda m: m.group(0).replace("/logix", "/logiq"),
    ),
    (
        re.compile(r'^Documentation = "https://github\.com/[^/]+/logix/', re.MULTILINE),
        lambda m: m.group(0).replace("/logix/", "/logiq/"),
    ),
    (
        re.compile(r'^Changelog = "https://github\.com/[^/]+/logix/', re.MULTILINE),
        lambda m: m.group(0).replace("/logix/", "/logiq/"),
    ),
]


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

PROCESS_DIRS = ("src", "tests", "scripts", "examples", "docs")
PROCESS_ROOT_FILES = ("pyproject.toml", "README.md", "CHANGELOG.md", "CONTRIBUTING.md")
PROCESS_EXTENSIONS = {".py", ".md", ".toml", ".rst", ".txt", ".cfg", ".ini"}


def collect_files() -> list[Path]:
    files: list[Path] = []
    for name in PROCESS_ROOT_FILES:
        p = ROOT / name
        if p.exists():
            files.append(p)
    for d in PROCESS_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for ext in PROCESS_EXTENSIONS:
            for p in base.rglob(f"*{ext}"):
                if "__pycache__" in p.parts:
                    continue
                files.append(p)
    return sorted(set(files))


def is_src_file(path: Path) -> bool:
    return (ROOT / "src") in path.parents


# ---------------------------------------------------------------------------
# Replacement
# ---------------------------------------------------------------------------


def apply_replacements(
    text: str,
    rules: list[tuple[re.Pattern[str], str]],
) -> tuple[str, int]:
    total = 0
    for pattern, repl in rules:
        if callable(repl):
            text, n = pattern.subn(repl, text)
        else:
            text, n = pattern.subn(repl, text)
        total += n
    return text, total


def process_file(path: Path, *, dry_run: bool) -> tuple[int, bool]:
    """Return (replacements_made, file_changed)."""
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0, False

    text = original
    total = 0

    if path.name == "pyproject.toml":
        text, n = apply_replacements(text, PYPROJECT_REPLACEMENTS)
        total += n
    elif is_src_file(path):
        text, n1 = apply_replacements(text, IMPORT_REPLACEMENTS)
        text, n2 = apply_replacements(text, SRC_AGGRESSIVE)
        total += n1 + n2
    else:
        text, n = apply_replacements(text, IMPORT_REPLACEMENTS)
        total += n

    if text == original:
        return 0, False

    if not dry_run:
        path.write_text(text, encoding="utf-8")

    return total, True


# ---------------------------------------------------------------------------
# Report remaining occurrences
# ---------------------------------------------------------------------------


def remaining_lowercase_logix(
    files: list[Path],
) -> list[tuple[Path, int, str]]:
    """
    Find remaining lowercase ``logix`` references that were NOT renamed.
    Excludes:
      - ``Logix`` (capital L)
      - ``logix`` followed by ``_`` (handled by import replacements)
      - ``logix.`` when preceded by ``from `` or ``import `` — already renamed
    Useful for manual review of prose in docs.
    """
    pattern = re.compile(r"\blogix\b(?!_)")
    remaining: list[tuple[Path, int, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in pattern.finditer(line):
                start = max(0, m.start() - 20)
                end = min(len(line), m.end() + 20)
                snippet = line[start:end].strip()
                remaining.append((path, lineno, snippet))
    return remaining


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would change; do not modify files"
    )
    parser.add_argument("--skip-verify", action="store_true", help="skip pytest after rename")
    args = parser.parse_args(argv)

    # Snapshot files BEFORE any changes.
    files = collect_files()
    print(f"Found {len(files)} files to scan.")

    # ---- Phase 1: content rewrites -------------------------------------
    print("\n=== Content rewrites ===")
    changed_files: list[Path] = []
    total_replacements = 0

    for path in files:
        n, changed = process_file(path, dry_run=args.dry_run)
        if changed:
            changed_files.append(path)
            total_replacements += n
            action = "would change" if args.dry_run else "changed"
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                rel = path
            print(f"  {action}: {rel}  ({n} replacements)")

    print(f"\n{len(changed_files)} files, {total_replacements} replacements.")

    # ---- Phase 2: directory renames ------------------------------------
    print("\n=== Directory renames ===")
    conflicts: list[tuple[str, str]] = []
    for old, new in DIR_RENAMES:
        old_path = ROOT / old
        new_path = ROOT / new
        if not old_path.exists():
            print(f"  SKIP {old} (does not exist)")
            continue
        if new_path.exists():
            conflicts.append((old, new))
            print(f"  CONFLICT {new} already exists — cannot rename {old}")
            continue
        print(f"  {'would rename' if args.dry_run else 'renaming'}: {old} -> {new}")
        if not args.dry_run:
            shutil.move(str(old_path), str(new_path))

    if conflicts:
        print(
            "\nFAIL: some target directories already exist. Resolve manually.",
            file=sys.stderr,
        )
        return 1

    # ---- Phase 3: report remaining occurrences -------------------------
    print("\n=== Remaining 'logix' references (manual review) ===")
    # Re-collect files (paths may have changed under src/).
    files_after = collect_files() if not args.dry_run else files
    remaining = remaining_lowercase_logix(files_after)

    if not remaining:
        print("  (none — clean rename)")
    else:
        for path, lineno, snippet in remaining[:60]:
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                rel = path
            print(f"  {rel}:{lineno}: ...{snippet}...")
        if len(remaining) > 60:
            print(f"  ... and {len(remaining) - 60} more")
        print(
            "\n  These are likely variable names (e.g. ``logix = Logix()``), "
            "prose in docs,\nor references in comments. Review and adjust "
            "manually if desired.\nThe class name ``Logix`` is preserved "
            "by design."
        )

    if args.dry_run:
        print("\ndry-run complete. No files were modified.")
        return 0

    # ---- Phase 4: verify ------------------------------------------------
    if args.skip_verify:
        print("\nSkipping pytest (--skip-verify).")
    else:
        print("\n=== Running pytest ===")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q"],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print(
                "\nFAIL: pytest failed after rename.\n"
                "Review the changes above and fix any remaining references\n"
                "manually, then re-run pytest.",
                file=sys.stderr,
            )
            return 1
        print("\nAll tests pass.")

    # ---- Next steps ----------------------------------------------------
    print("\n" + "=" * 60)
    print("Rename complete. Next steps:")
    print("=" * 60)
    print("  1. Reinstall the editable package:")
    print('       pip install -e ".[dev]"')
    print("  2. Verify import + quick smoke test:")
    print('       python -c "from logiq import Logix; print(Logix)"')
    print("  3. Review changes:")
    print("       git status")
    print("       git diff --stat")
    print("  4. Stage the rename (git shows it as delete+add):")
    print("       git add -A")
    print("  5. Update external references:")
    print("       - GitHub repo name (manual, if renaming)")
    print("       - CI workflows referencing 'logix'")
    print("       - Any bookmarks, badges, external docs")
    print("  6. Commit:")
    print('       git commit -m "Rename package to logiq"')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

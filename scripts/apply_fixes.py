#!/usr/bin/env python3
"""
Apply the four test-failure fixes after the ruff/mypy cleanup.

Fixes:
  1. src/execgate_ai/prompt_json_mode.py — whitespace-only system string
     should not be prepended as a bare "\n\n".
  2. tests/core/test_schema_inference.py — restore `int = None` (the
     ruff UP007 autofix rewrote it to `int | None`, which defeats the
     test's purpose).
  3. tests/mcp/test_wire_protocol.py — `.inputSchema` → `.input_schema`
     (FastMCP 4.1.x renamed the attribute; `filterwarnings = ["error"]`
     turns the deprecation warning into a failure).
  4. tests/mcp/test_wire_protocol.py — broaden the unknown-tool
     assertion; FastMCP intercepts unknown tools before dispatching to
     the handler, so the error message is FastMCP's, not Logiq's.

Idempotent: safe to run more than once. If a fix is already applied, it
prints "already applied" and skips.

Usage:
    python scripts/apply_fixes.py --dry-run   # preview
    python scripts/apply_fixes.py             # apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fix 1: prompt_json_mode — skip whitespace-only system string
# ---------------------------------------------------------------------------


def fix_prompt_json_mode(dry_run: bool) -> str:
    path = ROOT / "src" / "execgate_ai" / "prompt_json_mode.py"
    if not path.exists():
        return f"SKIP (missing): {path.relative_to(ROOT)}"

    text = _read(path)
    old = "    if system:\n        parts.append(system.strip())"
    new = "    if system and system.strip():\n        parts.append(system.strip())"

    if new in text:
        return f"already applied: {path.relative_to(ROOT)}"
    if old not in text:
        return (
            f"MANUAL: {path.relative_to(ROOT)} — pattern not found. "
            f"The code may have changed. Check `if system:` in build()."
        )

    if not dry_run:
        _write(path, text.replace(old, new, 1))
    return f"{'would fix' if dry_run else 'fixed'}: {path.relative_to(ROOT)}"


# ---------------------------------------------------------------------------
# Fix 2: test_schema_inference — restore `int = None` case
# ---------------------------------------------------------------------------


def fix_schema_inference_test(dry_run: bool) -> str:
    path = ROOT / "tests" / "core" / "test_schema_inference.py"
    if not path.exists():
        return f"SKIP (missing): {path.relative_to(ROOT)}"

    text = _read(path)

    # Match either the ruff-rewritten form or the original, and normalize
    # to the form the test actually needs.
    pattern = re.compile(
        r"def f\(x: (?:int \| None|int) = None\) -> int:"
        r"(\s*#[^\n]*)?\n"
        r"(?:        )?return 0",
    )
    replacement = (
        "def f(x: int = None) -> int:  # type: ignore[assignment]  # noqa: UP007\n        return 0"
    )

    if replacement in text:
        return f"already applied: {path.relative_to(ROOT)}"

    new_text, n = pattern.subn(replacement, text, count=1)
    if n == 0:
        return (
            f"MANUAL: {path.relative_to(ROOT)} — could not locate the "
            f"`def f(x: int = None)` test. Check around "
            f"test_default_none_without_optional_rejected."
        )

    if not dry_run:
        _write(path, new_text)
    return f"{'would fix' if dry_run else 'fixed'}: {path.relative_to(ROOT)}"


# ---------------------------------------------------------------------------
# Fix 3: test_wire_protocol — .inputSchema -> .input_schema
# ---------------------------------------------------------------------------


def fix_wire_protocol_attr(dry_run: bool) -> str:
    path = ROOT / "tests" / "mcp" / "test_wire_protocol.py"
    if not path.exists():
        return f"SKIP (missing): {path.relative_to(ROOT)}"

    text = _read(path)
    # Only rewrite attribute access: `.inputSchema`. Not dict keys
    # ("inputSchema": in a dict literal) — those are wire-format strings
    # and must stay camelCase.
    new_text = re.sub(r"\.inputSchema\b", ".input_schema", text)

    if new_text == text:
        return f"already applied: {path.relative_to(ROOT)}"

    count = len(re.findall(r"\.inputSchema\b", text))
    if not dry_run:
        _write(path, new_text)
    return f"{'would fix' if dry_run else 'fixed'}: {path.relative_to(ROOT)} ({count} occurrences)"


# ---------------------------------------------------------------------------
# Fix 4: test_wire_protocol — broaden unknown-tool assertion
# ---------------------------------------------------------------------------

_OLD_UNKNOWN_ASSERT = """    assert result.is_error
    assert "UNKNOWN_CAPABILITY" in result.content[0].text"""

_NEW_UNKNOWN_ASSERT = """    assert result.is_error
    # FastMCP intercepts unknown tools before dispatching to the handler,
    # so the error message is FastMCP's ("Unknown tool: ..."), not Logiq's
    # UNKNOWN_CAPABILITY. Either way, the handler was never invoked and
    # the tool does not exist. Accept both forms.
    text = result.content[0].text
    assert "does_not_exist" in text
    assert "Unknown tool" in text or "UNKNOWN_CAPABILITY" in text"""


def fix_unknown_tool_assertion(dry_run: bool) -> str:
    path = ROOT / "tests" / "mcp" / "test_wire_protocol.py"
    if not path.exists():
        return f"SKIP (missing): {path.relative_to(ROOT)}"

    text = _read(path)

    if _NEW_UNKNOWN_ASSERT in text:
        return f"already applied: {path.relative_to(ROOT)} (unknown tool)"

    if _OLD_UNKNOWN_ASSERT not in text:
        return (
            f"MANUAL: {path.relative_to(ROOT)} — could not locate the "
            f"unknown-tool assertion. Check test_unknown_tool_rejected."
        )

    if not dry_run:
        _write(path, text.replace(_OLD_UNKNOWN_ASSERT, _NEW_UNKNOWN_ASSERT, 1))
    return f"{'would fix' if dry_run else 'fixed'}: {path.relative_to(ROOT)} (unknown tool)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change; do not modify files",
    )
    args = parser.parse_args(argv)

    print(f"Repo root: {ROOT}")
    print(f"Mode: {'dry-run' if args.dry_run else 'apply'}\n")

    fixes = [
        ("prompt_json_mode whitespace guard", fix_prompt_json_mode),
        ("test_schema_inference int=None", fix_schema_inference_test),
        ("test_wire_protocol .input_schema", fix_wire_protocol_attr),
        ("test_wire_protocol unknown-tool assertion", fix_unknown_tool_assertion),
    ]

    results: list[tuple[str, str]] = []
    for label, fn in fixes:
        try:
            result = fn(args.dry_run)
        except Exception as e:
            result = f"ERROR: {type(e).__name__}: {e}"
        results.append((label, result))
        print(f"  [{label}]")
        print(f"    {result}")

    # Summary
    fixed = sum(1 for _, r in results if "fixed" in r and "already" not in r)
    manual = sum(1 for _, r in results if r.startswith("MANUAL"))
    errors = sum(1 for _, r in results if r.startswith("ERROR"))
    skipped = sum(1 for _, r in results if r.startswith("SKIP"))

    print()
    print(f"Summary: {fixed} fixed, {manual} manual, {skipped} skipped, {errors} errors")

    if errors:
        return 1
    if manual:
        print("\nSome fixes need manual attention. See the lines above.")
        return 2
    if args.dry_run:
        print("\nDry run complete. Re-run without --dry-run to apply.")
        return 0

    print("\nNext:")
    print("  pytest tests -q")
    print("  ruff check src tests scripts")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

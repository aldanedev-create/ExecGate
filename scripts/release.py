#!/usr/bin/env python3
"""
Bump the version, update the changelog, and prepare a git tag.

Steps:

  1. Read current version from pyproject.toml.
  2. Compute new version (--major / --minor / --patch, or --version X.Y.Z).
  3. Update pyproject.toml ``version = "..."``.
  4. Update src/execgate/__init__.py ``__version__ = "..."``.
  5. Rename ``## [Unreleased]`` in CHANGELOG.md to
     ``## [X.Y.Z] - YYYY-MM-DD`` and insert a fresh ``## [Unreleased]``.
  6. git add the three files, git commit, git tag.
  7. With --push, also git push origin main --tags.

Flags:

  --major / --minor / --patch   bump type
  --version X.Y.Z               explicit version (mutually exclusive with above)
  --push                        push the commit and tag to origin
  --dry-run                     print what would change; do not modify

Exit codes: 0 success, 1 failure, 3 user cancelled.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "logiq" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"

_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def _current_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if not m:
        raise SystemExit("FAIL: could not find version in pyproject.toml")
    return m.group(1)


def _bump(version: str, kind: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"FAIL: version {version!r} is not X.Y.Z")
    major, minor, patch = map(int, parts)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"FAIL: unknown bump kind {kind!r}")


def _replace_version(path: Path, regex: re.Pattern[str], new: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, n = regex.subn(
        lambda m: m.group(0).replace(m.group(1), new),
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit(f"FAIL: could not update version in {path}")
    path.write_text(new_text, encoding="utf-8")


def _update_changelog(new_version: str, date: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    # Find the Unreleased header.
    unreleased_re = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
    m = unreleased_re.search(text)
    if not m:
        raise SystemExit("FAIL: CHANGELOG.md has no '## [Unreleased]' header; refusing to guess.")
    # Find the next '## [' after Unreleased (or EOF).
    after = text[m.end() :]
    next_release = re.search(r"^## \[", after, re.MULTILINE)
    body_end = m.end() + (next_release.start() if next_release else len(after))
    body = text[m.end() : body_end].strip()

    replacement = (
        f"## [Unreleased]\n\n_(no changes yet)_\n\n## [{new_version}] - {date}\n\n{body}\n\n"
    )
    new_text = text[: m.start()] + replacement + text[body_end:]
    CHANGELOG.write_text(new_text, encoding="utf-8")


def _run(label: str, cmd: list[str], *, dry_run: bool) -> None:
    print(f"$ {' '.join(cmd)}")
    if dry_run:
        return
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"FAIL: {label} (exit {result.returncode})")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--major", action="store_true")
    group.add_argument("--minor", action="store_true")
    group.add_argument("--patch", action="store_true")
    group.add_argument("--version", metavar="X.Y.Z")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    current = _current_version()
    if args.version:
        new_version = args.version
        if not re.fullmatch(r"\d+\.\d+\.\d+", new_version):
            raise SystemExit(f"FAIL: --version {new_version!r} is not X.Y.Z")
    else:
        kind = "major" if args.major else "minor" if args.minor else "patch"
        new_version = _bump(current, kind)

    date = dt.date.today().isoformat()
    print(f"current:  {current}")
    print(f"new:      {new_version}  ({date})")

    if args.dry_run:
        print("\ndry-run: would update pyproject.toml, __init__.py, CHANGELOG.md")
        print(f"dry-run: would commit 'Release v{new_version}' and tag v{new_version}")
        return 0

    response = input("\nProceed? [y/N] ").strip().lower()
    if response not in ("y", "yes"):
        print("cancelled.", file=sys.stderr)
        return 3

    _replace_version(PYPROJECT, _VERSION_RE, new_version)
    _replace_version(INIT, _INIT_VERSION_RE, new_version)
    _update_changelog(new_version, date)

    _run(
        "git add",
        ["git", "add", str(PYPROJECT), str(INIT), str(CHANGELOG)],
        dry_run=False,
    )
    _run(
        "git commit",
        ["git", "commit", "-m", f"Release v{new_version}"],
        dry_run=False,
    )
    _run(
        "git tag",
        ["git", "tag", "-a", f"v{new_version}", "-m", f"Release v{new_version}"],
        dry_run=False,
    )

    if args.push:
        _run(
            "git push origin main",
            ["git", "push", "origin", "main"],
            dry_run=False,
        )
        _run(
            "git push --tags",
            ["git", "push", "--tags"],
            dry_run=False,
        )
    else:
        print("\nlocal commit and tag created; push when ready:")
        print("  git push origin main && git push --tags")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

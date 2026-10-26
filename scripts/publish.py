#!/usr/bin/env python3
"""
Build and upload to PyPI or TestPyPI.

Default flow:

  1. Refuse if the git working tree is dirty (unless --force).
  2. Run preflight.py (unless --skip-preflight).
  3. python -m build
  4. python -m twine check dist/*
  5. Prompt for confirmation (skipped with --yes).
  6. python -m twine upload dist/*

Flags:

  --test            upload to TestPyPI instead of PyPI
  --dry-run         stop after twine check; do not upload
  --skip-preflight  skip preflight (NOT RECOMMENDED)
  --force           allow publish from a dirty tree
  --yes             skip the confirmation prompt

Environment:

  TWINE_USERNAME / TWINE_PASSWORD, or a ~/.pypirc file. For TestPyPI
  with ~/.pypirc, use a section named ``testpypi``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("WARN: not a git repo, skipping clean-tree check", file=sys.stderr)
        return True
    return result.stdout.strip() == ""


def _run(label: str, cmd: list[str]) -> int:
    print(f"\n=== {label} ===")
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\nFAIL: {label} (exit {result.returncode})", file=sys.stderr)
        sys.exit(1)
    return result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="upload to TestPyPI instead of PyPI")
    parser.add_argument("--dry-run", action="store_true",
                        help="build and check only; do not upload")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="skip preflight.py")
    parser.add_argument("--force", action="store_true",
                        help="allow publish from a dirty working tree")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    target_name = "TestPyPI" if args.test else "PyPI"

    if not args.force and not _git_clean():
        print(
            "FAIL: git working tree is dirty. Commit or stash first, "
            "or pass --force.",
            file=sys.stderr,
        )
        return 1

    if not args.skip_preflight:
        _run("preflight", [sys.executable, str(ROOT / "scripts" / "preflight.py")])
    else:
        print("WARN: --skip-preflight set; tests and build checks were not run.")

        # Even with --skip-preflight, we still build.
        _run("build", [sys.executable, "-m", "build"])

    dist = ROOT / "dist"
    if not dist.exists() or not list(dist.iterdir()):
        print("FAIL: dist/ is empty after build", file=sys.stderr)
        return 1

    _run("twine check", [sys.executable, "-m", "twine", "check", "dist/*"]
         if False else [sys.executable, "-m", "twine", "check",
                        *map(str, dist.iterdir())])

    if args.dry_run:
        print(f"\ndry-run: would upload to {target_name}. Files in dist/:")
        for f in sorted(dist.iterdir()):
            print(f"  {f.name}")
        return 0

    if not args.yes:
        files = sorted(f.name for f in dist.iterdir())
        print(f"\nAbout to upload to {target_name}:")
        for f in files:
            print(f"  {f}")
        response = input("\nProceed? [y/N] ").strip().lower()
        if response not in ("y", "yes"):
            print("cancelled.", file=sys.stderr)
            return 3

    upload_cmd = [sys.executable, "-m", "twine", "upload"]
    if args.test:
        upload_cmd += ["--repository", "testpypi"]
    upload_cmd += [str(f) for f in sorted(dist.iterdir())]
    _run(f"twine upload -> {target_name}", upload_cmd)

    print(f"\npublished to {target_name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
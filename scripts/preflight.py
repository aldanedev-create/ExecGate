#!/usr/bin/env python3
"""
All checks that must pass before a release.

Runs, in order, stopping at the first failure:

  1. ruff check src tests
  2. ruff format --check src tests
  3. mypy src
  4. check_imports.py          (core must be stdlib-only)
  5. pytest                    (full suite)
  6. python -m build           (sdist + wheel)
  7. verify_wheel.py           (inspect the wheel)

Exit 0 on all pass, 1 on any failure. Console output names the failing
step, so it's obvious where to look.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _run(label: str, cmd: list[str]) -> None:
    print(f"\n=== {label} ===")
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\nFAIL: {label} (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def _run_py(label: str, script: Path, *args: str) -> None:
    _run(label, [sys.executable, str(script), *args])


def main() -> int:
    try:
        _run("ruff check", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"])
        _run(
            "ruff format",
            [sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
        )
        _run("mypy", [sys.executable, "-m", "mypy", "src"])
        _run_py("check_imports", SCRIPTS / "check_imports.py")
        _run("pytest", [sys.executable, "-m", "pytest"])
        _run("build", [sys.executable, "-m", "build"])

        wheels = sorted((ROOT / "dist").glob("*.whl"))
        if not wheels:
            print("FAIL: build produced no wheels", file=sys.stderr)
            return 1
        _run_py("verify_wheel", SCRIPTS / "verify_wheel.py", str(wheels[-1]))
    except SystemExit as e:
        # _run raises SystemExit to short-circuit; report and re-raise.
        if e.code and e.code != 0:
            print(
                "\npreflight FAILED — fix the errors above before publishing.",
                file=sys.stderr,
            )
        raise

    print("\npreflight OK — ready to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

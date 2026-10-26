#!/usr/bin/env python3
"""
Inspect a built wheel for the properties Logix promises.

Verifies:

  - expected packages present: logix, execgate_pydantic, execgate_ai, execgate_mcp
  - ``py.typed`` present in each package
  - tests/, scripts/, docs/ NOT in the wheel
  - core declares no unconditional runtime dependency
    (no ``Requires-Dist`` without ``; extra ==``)
  - ``Requires-Python`` is ``>=3.11``

Usage:

    python scripts/verify_wheel.py dist/logix-0.1.0-py3-none-any.whl

Exit 0 on pass, 1 on any failure.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

EXPECTED_PACKAGES = ("execgate", "execgate_pydantic", "execgate_ai", "execgate_mcp")
FORBIDDEN_PREFIXES = ("tests/", "scripts/", "docs/", "examples/")


def _metadata_entries(zf: zipfile.ZipFile) -> str | None:
    for name in zf.namelist():
        if name.endswith(".dist-info/METADATA"):
            return zf.read(name).decode("utf-8", errors="replace")
    return None


def _field(metadata: str, field: str) -> list[str]:
    prefix = field.lower() + ":"
    values: list[str] = []
    for line in metadata.splitlines():
        if line.lower().startswith(prefix):
            values.append(line.split(":", 1)[1].strip())
    return values


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verify_wheel.py <wheel-path>", file=sys.stderr)
        return 1

    wheel = Path(argv[1])
    if not wheel.exists():
        print(f"FAIL: wheel not found: {wheel}", file=sys.stderr)
        return 1

    failures: list[str] = []

    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()

        # 1. Each package present.
        for pkg in EXPECTED_PACKAGES:
            if f"{pkg}/__init__.py" not in names:
                failures.append(f"missing package: {pkg}/__init__.py")

        # 2. py.typed present.
        for pkg in EXPECTED_PACKAGES:
            if f"{pkg}/py.typed" not in names:
                failures.append(f"missing type marker: {pkg}/py.typed")

        # 3. No dev-only directories.
        for name in names:
            for prefix in FORBIDDEN_PREFIXES:
                if name.startswith(prefix):
                    failures.append(f"forbidden path in wheel: {name} (prefix {prefix!r})")
                    break

        # 4. Metadata.
        metadata = _metadata_entries(zf)
        if metadata is None:
            failures.append("missing METADATA")
        else:
            python_req = _field(metadata, "Requires-Python")
            if not python_req:
                failures.append("missing Requires-Python")
            elif not any(">=3.11" in v or ">=3.12" in v or ">=3.13" in v for v in python_req):
                failures.append(f"Requires-Python must be >=3.11, got {python_req}")

            # No unconditional runtime deps.
            for req in _field(metadata, "Requires-Dist"):
                if "extra ==" not in req:
                    failures.append(
                        f"unconditional Requires-Dist in wheel: {req!r} "
                        f"(core must have zero runtime deps)"
                    )

    if failures:
        print(f"FAIL: {wheel.name}", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"OK: {wheel.name} passes all checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

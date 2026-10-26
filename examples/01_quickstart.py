"""
Quickstart: register a capability, run a plan.

Run:
    python examples/01_quickstart.py

No setup required — this is the smallest end-to-end example. It
demonstrates:
  - registering a Python function as a capability
  - the inferred schema
  - running a single-call plan
  - running a plan that fails verification

The decorated function is still normally callable — the first print
shows that. The rest of the script shows the boundary working.
"""

import json

from execgate import Logix


def main() -> None:
    logix = Logix()

    # --- Register ---
    @logix.capability
    def add(a: int, b: int) -> int:
        "Add two integers."
        return a + b

    # The original function is unchanged.
    print(f"add(2, 3) = {add(2, 3)}")

    # --- The inferred schema ---
    print("\nInferred catalog:")
    print(json.dumps(logix.tools.format("json"), indent=2))

    # --- Success ---
    result = logix.run({"call": "add", "with": {"a": 10, "b": 20}})
    print(f"\nSuccess: ok={result.ok}, value={result.value}")

    # --- Failure: unknown capability ---
    result = logix.run({"call": "does_not_exist", "with": {}})
    print(f"\nUnknown capability: code={result.errors[0].code}")

    # --- Failure: schema violation ---
    result = logix.run({"call": "add", "with": {"a": "ten", "b": 20}})
    print(f"Bad argument: code={result.errors[0].code}, path={result.errors[0].path}")

    # --- Failure: extra field ---
    result = logix.run({"call": "add", "with": {"a": 1, "b": 2, "c": 3}})
    print(f"Extra field: code={result.errors[0].code}")


if __name__ == "__main__":
    main()
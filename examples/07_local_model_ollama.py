"""
Local model with JSON-mode prompt.

Run:
    python examples/07_local_model_ollama.py

Requires:
    pip install ollama
    ollama pull llama3.1
    (with Ollama running in the background)

Demonstrates:
  - logiq_ai.prompt_json_mode.build(...)  — system prompt for JSON mode
  - LocalAdapter.parse_proposal(...)      — parse a JSON response
  - the same logix.run(plan) as every other example

If you don't have Ollama running, the script prints the prompt it would
have sent and exits. The prompt is the interesting part for
understanding what the model sees.
"""

import json
import sys

from logiq import Logix
from logiq_ai import get_adapter
from logiq_ai.prompt_json_mode import build


def main() -> None:
    logix = Logix()

    @logix.capability(effects="read")
    def get_order(order_id: int) -> dict[str, float]:
        "Retrieve an order by its ID."
        return {"id": float(order_id), "total": 50.0}

    # 1. Build the system prompt from the catalog.
    system_prompt = build(
        logix.tools.describe(),
        system="You are a support agent. Use tools to look up orders.",
    )

    print("=== System prompt (what the model sees) ===")
    print(system_prompt[:800] + "\n... [truncated]\n")

    # 2. Call the model (Ollama) — or simulate the response.
    try:
        import ollama
    except ImportError:
        print("Ollama not installed. Install with: pip install ollama")
        print("\nSimulating a response instead:")
        response = {
            "response": '{"call": "get_order", "with": {"order_id": 502}}',
        }
    else:
        response = ollama.chat(
            model="llama3.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "What is the total on order 502?"},
            ],
        )

    # 3. Parse the response into a neutral plan.
    adapter = get_adapter("local")
    plan = adapter.parse_proposal(response)
    print(f"=== Parsed plan ===")
    print(json.dumps(plan, indent=2))

    # 4. Run it through Logiq.
    result = logix.run(plan)
    print(f"\n=== Result ===")
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
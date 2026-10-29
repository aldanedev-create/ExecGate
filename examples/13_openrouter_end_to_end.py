"""
OpenRouter + Logiq example.

Requires:
    pip install "logiq[ai]" openai
    export OPENROUTER_API_KEY="sk-or-v1-..."

Run:
    python examples/13_openrouter_end_to_end.py

Demonstrates:
  - OpenRouter via the OpenAI SDK (base_url override)
  - the five-step loop: catalog -> model -> parse -> verify -> run
  - a multi-turn conversation with tool calls
  - error recovery: a rejected plan is fed back, model corrects
"""

import json
import os

import openai

from execgate import Logix, Allow, Deny
from execgate_ai import get_adapter


# --- Domain ---
logix = Logix()

ORDERS = {
    502: {"id": 502, "owner": "alice", "state": "delivered", "total": 50.0},
    777: {"id": 777, "owner": "bob", "state": "shipped", "total": 900.0},
}
REFUNDED: set[int] = set()


@logix.capability(effects="read")
def get_order(order_id: int) -> dict[str, float]:
    "Retrieve an order by its ID."
    order = ORDERS[order_id]
    return {"id": float(order["id"]), "total": order["total"]}


@logix.capability(effects="read")
def list_my_orders() -> list[int]:
    "List all order IDs."
    return list(ORDERS.keys())


@logix.capability(effects="write")
def refund_order(order_id: int) -> dict[str, float]:
    "Issue a full refund for an order (fetches total internally)."
    order = ORDERS[order_id]
    REFUNDED.add(order_id)
    return {"refunded": float(order_id), "amount": order["total"]}


def refund_policy(args, ctx):
    order = ORDERS[args["order_id"]]
    if order["owner"] != ctx.principal:
        return Deny("NOT_OWNER", "caller does not own this order")
    if order["state"] != "delivered":
        return Deny("NOT_DELIVERED", "order is not refundable")
    return Allow()


logix.authorize(refund_order, check=refund_policy)


# --- OpenRouter client ---
# OpenRouter exposes an OpenAI-compatible chat completions endpoint.
# Only base_url and api_key differ from a direct OpenAI setup.
client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# OpenRouter uses provider/model slugs. Pick one that supports tool calling.
MODEL = "openai/gpt-4o"
# Free alternative (supports tool calling):
# MODEL = "qwen/qwen3.6-plus:free"

adapter = get_adapter("openai")  # OpenRouter uses OpenAI's tool shape


def chat_turn(messages: list[dict], user_message: str, principal: str = "alice") -> list[dict]:
    """One conversational turn. Loops until the model stops proposing tools."""
    messages = messages + [{"role": "user", "content": user_message}]
    ctx = logix.context(principal=principal)

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=adapter.format_tools(logix.tools.describe()),
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content})
            print(f"\n[assistant]: {msg.content}\n")
            return messages

        plan = adapter.parse_proposal(response)
        print(f"[model proposed]: {plan}")

        result = logix.run(plan, context=ctx)
        print(f"[logiq result]: ok={result.ok}")

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        tool_result = (
            {"ok": True, "value": result.value}
            if result.ok
            else {"ok": False, "errors": [e.to_dict() for e in result.errors]}
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": msg.tool_calls[0].id,
                "content": json.dumps(tool_result),
            }
        )


if __name__ == "__main__":
    messages = []
    messages = chat_turn(messages, "What is the total on order 502?")
    messages = chat_turn(messages, "List all my orders.")
    messages = chat_turn(messages, "Refund order 502.")
    print(f"\n502 refunded: {502 in REFUNDED}")

 <div align="center">

  <a href="https://aldanedev-create.github.io/ExecGate-doc/">
    <img src="https://raw.githubusercontent.com/aldanedev-create/ExecGate/main/assets/execgate_logo.png" alt="ExecGate logo" width="200">
  </a>

# ExecGate

**Verified execution for AI-generated plans.**

The AI proposes. ExecGate verifies. Trusted code executes.

[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](#project-status)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/aldanedev-create/ExecGate/blob/main/LICENSE)
[![Core: zero deps](https://img.shields.io/badge/core-zero%20runtime%20deps-success)](https://github.com/aldanedev-create/ExecGate/blob/main/docs/system-design.md)

[Documentation](https://aldanedev-create.github.io/ExecGate-doc/) · [Getting Started](https://aldanedev-create.github.io/ExecGate-doc/#getting-started/index) · [API Reference](https://aldanedev-create.github.io/ExecGate-doc/#api-reference) · [Examples](https://github.com/aldanedev-create/ExecGate/tree/main/examples) · [Security](https://aldanedev-create.github.io/ExecGate-doc/#security)

</div>

---

ExecGate is a **verification boundary between AI-generated plans and trusted Python code**.

It validates proposed actions against registered capabilities, schemas, policies, references, and live application state before normal handler execution.

```python
from execgate import Logix

logix = Logix()


@logix.capability
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


result = logix.run({
    "call": "add",
    "with": {"a": 10, "b": 20},
})

if result.ok:
    print(result.value)  # 30
else:
    print(result.errors)
```

ExecGate infers schemas from type annotations, extracts descriptions from docstrings, and registers capabilities. Your handlers remain ordinary Python functions.

**ExecGate does not decide what your application should permit. It enforces the rules you define.**

## Why ExecGate?

AI applications increasingly let models select tools, generate structured arguments, and propose actions. Your application still needs to verify that those proposals are valid and authorized.

ExecGate provides a boundary for checks such as:

- **Capability validation** — reject unknown or invented capability names.
- **Schema validation** — validate arguments and enforce declared types.
- **Reference validation** — reject malformed plans and invalid dependencies.
- **Policy enforcement** — check configured rules before execution.
- **Live-state authorization** — evaluate application state when an action is verified and executed.
- **Human approval** — add approval gates for sensitive operations.
- **Idempotency** — help prevent duplicate execution when retries occur.
- **Failure handling** — distinguish verification rejection from execution failure.

Explore the [System Design](https://aldanedev-create.github.io/ExecGate-doc/#system-design) and [Security Model](https://aldanedev-create.github.io/ExecGate-doc/#security).

## Installation

```bash
pip install execgate
```

Optional integrations:

```bash
pip install "execgate[pydantic]"  # Pydantic model support
pip install "execgate[ai]"        # AI provider adapters
pip install "execgate[mcp]"       # MCP server and proxy
pip install "execgate[all]"       # All configured extras
```

**Requirements:** Python 3.11 or later.

The core package has zero third-party runtime dependencies. Optional integrations extend the core without making Pydantic, FastMCP, or provider SDKs mandatory for `import execgate`.

## Three ways to use ExecGate

### 1. Use it as a dispatcher

You don't need an AI model to benefit from schema-checked capability execution.

```python
result = logix.run({
    "call": "add",
    "with": {"a": 1, "b": 2},
})
```

This can be useful in scripts, tests, command-line tools, and webhook handlers.

### 2. Connect an AI model

Let a model propose a plan, then pass that proposal through ExecGate's verification pipeline.

```python
catalog = logix.tools.format("openai")
plan = adapter.parse_proposal(ai_response)

result = logix.run(plan, context=ctx)
```

The AI proposes. ExecGate verifies. Your handler executes only if the required checks pass.

### 3. Separate verification from execution

For workflows that need explicit approval or additional control, verify first and execute afterward.

```python
report = logix.verify(plan, context=ctx)

approval = ask_human(report.verified_plan)

result = logix.execute(
    report.verified_plan,
    context=ctx,
    approval=approval,
)
```

This separation lets you introduce approval gates, live-state invariants, and bounded retries into your application workflow.

Start with the [Getting Started Guide](https://aldanedev-create.github.io/ExecGate-doc/#getting-started/index) or follow [Lesson 01: Refund Workflow](https://aldanedev-create.github.io/ExecGate-doc/#lessons/01-refund-workflow).

## Works with any AI that emits JSON

ExecGate's core is provider-neutral. It can process plans from hosted models, local models, scripts, or other sources.

```python
catalog = logix.tools.format("json")    # Provider-neutral format
catalog = logix.tools.format("openai")  # Optional provider format
```

Provider adapters are optional translators, not a requirement. A plan from an AI provider and a plan written by hand go through the same verification pipeline.

See [AI Integration](https://aldanedev-create.github.io/ExecGate-doc/#ai-integration).

## MCP integration

ExecGate supports both MCP server and proxy workflows through the optional `execgate_mcp` package.

### Server mode

Expose registered ExecGate capabilities to an MCP client.

```python
from execgate_mcp import LogixMCPServer

server = LogixMCPServer(logix, name="order-service")
server.run()
```

The example uses stdio transport. Calls are routed through `logix.run()`.

### Proxy mode

Verify calls to an upstream MCP server before forwarding them.

```python
from execgate_mcp import LogixMCPProxy

proxy = LogixMCPProxy(logix, "http://upstream/mcp")

await proxy.startup()

try:
    await proxy.run_async()
finally:
    await proxy.shutdown()
```

The `execgate_mcp` package follows the leaf-node architecture described in ADR-0007. It imports the public `Logix` API and shared types rather than reaching into the verifier, executor, or intermediate representation.

**Limitation:** MCP approval workflows have documented restrictions. Review the [MCP Guide](https://aldanedev-create.github.io/ExecGate-doc/#mcp) before designing an approval-dependent MCP deployment.

## How verification works

```text
AI / script / MCP client
          |
          | Untrusted proposal
          v
+--------------------------------------+
|               ExecGate               |
|                                      |
|  Parse -> Ground -> Verify           |
|                    |                 |
|                    v                 |
|              VerifiedPlan            |
|                    |                 |
|                    v                 |
|  Recheck invariants, approval,       |
|  and idempotency during execution    |
+--------------------|-----------------+
                     |
                     v
            Trusted handlers
          (database, payments, etc.)
```

The executor accepts a `VerifiedPlan`, not an arbitrary dictionary claiming to be verified. Dynamic checks are re-evaluated during execution immediately before the handler runs.

**Verification is not the same as authorization.** ExecGate can enforce the rules and checks implemented by your application, but it cannot invent missing business rules or guarantee that every permitted action is harmless.

Read the [System Design](https://aldanedev-create.github.io/ExecGate-doc/#system-design) and [Security](https://aldanedev-create.github.io/ExecGate-doc/#security) guides for the detailed model.

## What's included?

| Package | Purpose | Runtime dependencies |
|---|---|---|
| `execgate` | Registry, schema engine, verifier, executor, semantic layer | Python standard library |
| `execgate_pydantic` | Pydantic models as capability schemas | `pydantic>=2,<3` |
| `execgate_ai` | Provider-catalog adapters | None |
| `execgate_mcp` | MCP server and proxy | `fastmcp>=4,<5` |

Optional packages are not required to use the core dispatcher. The core's zero-dependency guarantee is also checked by the project's import-boundary tests.

## Documentation

The [ExecGate documentation site](https://aldanedev-create.github.io/ExecGate-doc/) contains guides, API references, architecture decisions, and security documentation.

| Guide | What you'll learn |
|---|---|
| [Getting Started](https://aldanedev-create.github.io/ExecGate-doc/#getting-started/index) | Build your first capability and plan |
| [Usage Model](https://aldanedev-create.github.io/ExecGate-doc/#usage-model) | Understand the developer, AI, and verification boundary |
| [System Design](https://aldanedev-create.github.io/ExecGate-doc/#system-design) | Follow the execution pipeline and failure model |
| [API Reference](https://aldanedev-create.github.io/ExecGate-doc/#api-reference) | Explore the public API |
| [Security](https://aldanedev-create.github.io/ExecGate-doc/#security) | Understand the threat model and security tests |
| [Semantic Layer](https://aldanedev-create.github.io/ExecGate-doc/#semantic-layer) | Learn about grounding, invariants, approval, and idempotency |
| [Plan Format](https://aldanedev-create.github.io/ExecGate-doc/#plan-format) | Understand plan structure, `$ref`, and versioning |
| [Schemas](https://aldanedev-create.github.io/ExecGate-doc/#schemas) | Learn about schema inference and strict types |
| [AI Integration](https://aldanedev-create.github.io/ExecGate-doc/#ai-integration) | Connect AI providers to ExecGate |
| [Writing an Adapter](https://aldanedev-create.github.io/ExecGate-doc/#writing-an-adapter) | Build a provider adapter |
| [MCP](https://aldanedev-create.github.io/ExecGate-doc/#mcp) | Configure server and proxy modes |
| [Production Guide](https://aldanedev-create.github.io/ExecGate-doc/#production-guide) | Review deployment, observability, and incident response |

The documentation source is available in [`docs/`](https://github.com/aldanedev-create/ExecGate/tree/main/docs). Architecture decision records are in [`docs/adr/`](https://github.com/aldanedev-create/ExecGate/tree/main/docs/adr).

## Examples

The repository includes standalone scripts in [`examples/`](https://github.com/aldanedev-create/ExecGate/tree/main/examples).

| Example | Demonstrates |
|---|---|
| [`01_quickstart.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/01_quickstart.py) | Register a capability and run a plan |
| [`02_ai_tool_catalog.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/02_ai_tool_catalog.py) | Describe and format tool catalogs |
| [`03_multistep_refs.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/03_multistep_refs.py) | Multi-step plans, `$ref`, and grounding |
| [`04_refund_with_approval.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/04_refund_with_approval.py) | Verify, request approval, and execute |
| [`05_pydantic_models.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/05_pydantic_models.py) | Use Pydantic models as schemas |
| [`06_fastapi_worker.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/06_fastapi_worker.py) | Embed ExecGate in a FastAPI worker |
| [`07_local_model_ollama.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/07_local_model_ollama.py) | Use a local model with JSON-mode prompting |
| [`08_write_your_own_adapter.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/08_write_your_own_adapter.py) | Write a custom provider adapter |
| [`09_mcp_server_quickstart.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/09_mcp_server_quickstart.py) | Expose capabilities to MCP clients |
| [`10_mcp_proxy_refund.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/10_mcp_proxy_refund.py) | Verify calls before forwarding upstream |
| [`11_mcp_approval_elicitation.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/11_mcp_approval_elicitation.py) | Explore approval in MCP deployments |
| [`12_xerj_native.py`](https://github.com/aldanedev-create/ExecGate/blob/main/examples/12_xerj_native.py) | Use XERJ search as a native capability |

Run the basic quick start with:

```bash
python examples/01_quickstart.py
```

Check each example's imports and requirements before running it; optional integrations may need their corresponding extras installed.

## Project status

**Version:** 0.1.0 · **Status:** Alpha · Active development

### Implemented

- The core pipeline: parsing, grounding, verification, execution-time rechecks, and output validation.
- Semantic-layer features for grounding, invariants, approval, idempotency, and bounded repair.
- Optional Pydantic, AI-provider, and MCP integrations.
- Security tests covering documented verification guarantees.
- Getting-started guides, lessons, API documentation, and architecture decision records.

### Known limitations and future work

- `logix.dry_run()` and `logix.explain()` are reserved names; their behavior is deferred.
- The default idempotency store is in-memory. Applications needing durable idempotency must implement the `IdempotencyStore` protocol using their own storage.
- By default an idempotent capability deduplicates on its arguments (scoped to tenant and principal), so two *legitimate* identical calls collapse into one. For operations that may repeat (payments, refunds), set `idempotency_key="context.request_id"` — see the [Semantic Layer](https://aldanedev-create.github.io/ExecGate-doc/#semantic-layer) docs.
- Approval tokens expire after `approval_ttl` seconds (default 900). Tokens are not revocable or single-use; keep the window short.
- Plan execution is sequential in version 0.1.0.
- MCP approval workflows have documented limitations.

**ExecGate is not yet production-ready.** Review the [Production Guide](https://aldanedev-create.github.io/ExecGate-doc/#production-guide) and [MCP limitations](https://aldanedev-create.github.io/ExecGate-doc/#mcp) before deployment.

## Security

ExecGate is security-adjacent software. Its verification boundary can enforce implemented checks, but it does not guarantee that handlers are correct, that business rules are complete, or that permitted actions are safe.

Please do not report security vulnerabilities through public GitHub issues. Follow the private disclosure process described in [CONTRIBUTING.md](https://github.com/aldanedev-create/ExecGate/blob/main/CONTRIBUTING.md#reporting-security-issues).

For the threat model, limitations, and guarantee-to-test mapping, see the [Security Guide](https://aldanedev-create.github.io/ExecGate-doc/#security).

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](https://github.com/aldanedev-create/ExecGate/blob/main/CONTRIBUTING.md).

```bash
git clone https://github.com/aldanedev-create/ExecGate.git
cd ExecGate
pip install -e ".[dev]"
pytest
python scripts/preflight.py
```

Key project constraints include:

- The core test suite must pass without Pydantic or FastMCP installed.
- `scripts/check_imports.py` checks the zero-dependency import boundary.
- `tests/mcp/test_leaf_node_boundary.py` checks the MCP adapter's architectural boundary.

Run the documented checks before submitting changes.

## License

ExecGate is licensed under the MIT License. See [LICENSE](https://github.com/aldanedev-create/ExecGate/blob/main/LICENSE).

---

<div align="center">

**Declare the intent. Verify the plan. Execute only what the application permits.**

</div>

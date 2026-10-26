# Logiq

**Verified execution for AI-generated plans.**

The AI proposes. Logiq verifies. Trusted code executes.

Logiq is a verification boundary between an AI's proposed action and the
trusted Python function that would carry it out. Models emit structured
JSON plans; Logix validates them against registered capabilities,
policies, references, and live state before any handler runs.

```python
from logiq import Logix

logix = Logix()

@logix.capability
def add(a: int, b: int) -> int:
    "Add two integers."
    return a + b

result = logix.run({"call": "add", "with": {"a": 10, "b": 20}})

if result.ok:
    print(result.value)   # 30
else:
    print(result.errors)
```

That's the whole quick start. The decorator infers schemas from type
annotations, extracts the docstring, registers the capability, and exposes
it to an AI as a tool description. The handler remains an ordinary Python
function and is still directly callable.

---

## What Logix does — and does not — guarantee

**It does guarantee**, as a testable property:

> A plan that fails Logix's required verification checks does not reach
> normal handler execution.

That covers mechanical failures: invented capabilities, wrong argument
types, malformed plans, dangling or cyclic references, statically
rejected policy, missing or mismatched approval, and live-state
authorization failures. Each is backed by a named test in
`tests/security/`.

**It does not claim** to prove that a model's natural-language claims are
true, infer business rules the developer did not encode, guarantee that a
handler behaves correctly, or prove that a permitted action is harmless.
Those remain the application's responsibility. The semantic layer —
`logix.authorize(...)`, `logix.require_approval(...)`,
`logix.grounding(...)` — shrinks that residual surface. It is engineered
minimization plus audit, not proof.

This precision is deliberate. "Eliminates hallucinations" is untestable;
"a plan that fails verification cannot reach a handler" is not.

---

## Works with any AI that emits JSON

The core is provider-neutral. `logix.tools.format("json")` returns a
JSON-Schema catalog that any client can read — a hosted model, a local
model, a script, or a human. Named provider adapters (`"openai"`,
`"anthropic"`, `"gemini"`, `"local"`) are **optional convenience
translators**, not requirements. Unknown providers fall back to the
neutral format. Writing your own adapter is ~30 lines and gives no access
to the trust boundary — see `docs/writing-an-adapter.md` and
`tests/adapters/contract.py`.

```python
catalog = logix.tools.format("json")        # always available
catalog = logix.tools.format("openai")      # optional adapter
```

The same guarantee that protects a hand-written plan protects an AI's
proposal. There is no privileged source.

---

## The three levels

**Level 1 — no AI yet.** Register functions, call `logix.run()` from a
script or test. Logix is useful on its own as a schema-enforcing
dispatcher.

**Level 2 — AI tool-calling.** Expose `logix.tools.format(...)` to a
model, receive its proposal, pass it to `logix.run()`. The common case.

**Level 3 — production agent.** Split `logix.verify()` and
`logix.execute()`, insert a human approval gate, attach live-state
authorization and grounding rules, bound the repair loop, and record
audit events.

```python
# Level 3: separate verification from execution
report = logix.verify(plan, context=ctx)
if not report.ok:
    return handle_errors(report.errors)

# Application-specific gate — human approval, extended review, etc.
approval = ask_human(report.verified_plan)

# Execute only the verified representation
result = logix.execute(report.verified_plan, context=ctx, approval=approval)
```

`verification` is **not** an authorization grant. `execute()` re-runs every
check that can be invalidated by live state (ADR-0004).

---

## What's in the box

| Package | Purpose | Runtime deps |
|---|---|---|
| `logiq` | Core: registry, schema engine, verifier, executor, semantic layer | **standard library only** |
| `logiq_pydantic` | Optional: use Pydantic models as capability schemas | `pydantic>=2,<3` |
| `logiq_ai` | Optional: provider-specific tool-catalog translation | none (pure data shaping) |
| `logiq_mcp` | Optional: MCP server mode + MCP proxy mode | `fastmcp>=4,<5` |

The core has **zero third-party runtime dependencies**. Optional
integrations extend it; they never become mandatory. `import logiq` never
touches Pydantic, FastMCP, or any provider SDK.

---

## Install

```bash
pip install logiq                # core, standard library only
pip install "logiq[pydantic]"    # optional richer models
pip install "logiq[ai]"          # optional provider adapters
pip install "logiq[mcp]"         # optional MCP integration
pip install "logiq[all]"         # everything, including dev tools
```

Python 3.11+.

---

## MCP integration

XERJ-style scenario: an MCP-capable client calls a search capability, or
an untrusted upstream MCP server needs a verification layer in front of
it.

**Server mode** — expose Logix capabilities to any MCP client:

```python
from logiq_mcp import LogixMCPServer

server = LogixMCPServer(logix, name="order-service")
server.run()   # stdio; every call goes through logix.run()
```

**Proxy mode** — verify calls before forwarding to an untrusted upstream:

```python
from logiq_mcp import LogixMCPProxy

proxy = LogixMCPProxy(logix, "http://upstream/mcp")
await proxy.startup()
try:
    await proxy.run_async()
finally:
    await proxy.shutdown()
```

See `docs/mcp.md` for the threat model and `docs/adr/0007-mcp-leaf-node-boundary.md`
for why `logiq_mcp` cannot touch the verifier or executor.

---

## Documentation

| Document | Covers |
|---|---|
| `docs/usage-model.md` | Who does what: developer, AI, and the boundary |
| `docs/system-design.md` | End-to-end pipeline, trust boundary, failure taxonomy |
| `docs/api-reference.md` | Every public API with stability markers |
| `docs/architecture.md` | Component map and design principles |
| `docs/plan-format.md` | Plan JSON, versions, `$ref` grammar, grounding rules |
| `docs/schemas.md` | Native schema inference and strict type semantics |
| `docs/security.md` | Threat model and the security test checklist |
| `docs/semantic-layer.md` | Grounding, live invariants, approval, idempotency |
| `docs/pydantic.md` | Optional Pydantic integration |
| `docs/ai-integration.md` | Provider-neutral catalog and adapter model |
| `docs/writing-an-adapter.md` | Custom adapter walkthrough |
| `docs/mcp.md` | MCP server and proxy modes |
| `docs/integrations/xerj.md` | XERJ search-engine integration |
| `docs/production-guide.md` | Deployment, observability, limits |
| `docs/adr/` | Architecture decision records |

---

## Examples

| Example | Shows |
|---|---|
| `examples/01_quickstart.py` | `@logix.capability` + `logix.run()` |
| `examples/02_ai_tool_catalog.py` | `logix.tools.describe()` / `.format()` |
| `examples/03_multistep_refs.py` | Multi-step plan with `$ref` grounding |
| `examples/04_refund_with_approval.py` | Level 3: verify → approve → execute |
| `examples/05_pydantic_models.py` | Pydantic models as capability schemas |
| `examples/06_fastapi_worker.py` | Framework-agnostic embedding |
| `examples/07_local_model_ollama.py` | Local model, JSON-mode prompt |
| `examples/08_write_your_own_adapter.py` | Reference adapter, ~30 lines |
| `examples/09_mcp_server_quickstart.py` | Expose capabilities to MCP clients |
| `examples/10_mcp_proxy_refund.py` | Verify calls before forwarding upstream |
| `examples/11_mcp_approval_elicitation.py` | Approval gate in MCP proxy mode |
| `examples/12_xerj_native.py` | XERJ search as a native capability |

---

## Project status

**0.1.0 — active development, alpha.**

- **Core (`src/logiq/`)** — implemented. The full pipeline (parse →
  grounding → verify → recheck → execute → output validation) works
  end to end. `dry_run` and `explain` are reserved by name.
- **Optional adapters** — `logiq_pydantic` and `logiq_ai` are implemented.
  `logiq_mcp` is implemented and covered by its own test suite.
- **Tests** — the suite in `tests/` covers core, semantic, security,
  Pydantic, adapters, integration, MCP, and fuzz paths. The security
  test checklist in `docs/security.md` is the source of truth.
- **Documentation** — the design docs (`usage-model.md`,
  `system-design.md`, `api-reference.md`) are the specification the
  code satisfies. When they disagree, the docs win.

The API is marked **stable** / **experimental** / **reserved** in
`docs/api-reference.md`. Breaking changes to stable APIs need a major
version. Experimental APIs may change between minor versions. Reserved
names (e.g. `dry_run`, `explain`) are fixed but have no implementation
guarantee yet.

Not production-ready: this is a reference implementation of a design.
Read `docs/system-design.md §11` before deploying.

---

## Development

```bash
git clone https://github.com/logix-dev/logix
cd logix
python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
pytest                       # full suite
pytest tests/security -m security -v   # security checklist only
python scripts/preflight.py  # ruff + mypy + imports + tests + wheel
```

See `CONTRIBUTING.md` for contribution rules, especially the leaf-node
discipline for adapters (ADR-0006, ADR-0007) and the requirement that
every security-relevant change ships with a matching test in
`tests/security/`.

---

## License

MIT. See `LICENSE`.

---

## The one-sentence summary

> The developer declares what is possible and what is permitted. The AI
> chooses what to attempt. Logix decides what actually happens.

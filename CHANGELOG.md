# Changelog

All notable changes to ExecGate are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

Because 0.x releases may change experimental APIs, this changelog marks
the stability of each entry:

- **stable** — part of the 0.1 contract; breaking changes need a major bump.
- **experimental** — present but semantics may change between minor versions.
- **reserved** — name fixed, behavior deferred; do not depend on it.

Error codes are part of the stable contract. Adding a code is a minor
change; renaming or removing one is a major change.

---

## [Unreleased]

_(no changes yet)_

---

## [0.1.0] - 2026-10-26

First release. Everything below is the initial implementation.

### Added

#### Core (`logiq`) — stable

- `Logix` engine with isolated registry, policy configuration, and
  schema settings. Multiple engines coexist in one process with no
  shared state.
- `@logix.capability` decorator: infers input and output schemas from
  type annotations, extracts the description from the docstring,
  registers the capability. The decorated function remains normally
  callable — no wrapper.
- Native schema engine:
  - Primitives: `int`, `float`, `str`, `bool`, `None`.
  - Containers: `list[X]`, `dict[str, X]`.
  - Unions: `Optional[X]`, `Union[X, Y]`.
  - Enums: `Literal[...]`.
  - Constraints via `Annotated`: `Gt`, `Ge`, `Lt`, `Le`, `MinLength`,
    `MaxLength`, `Pattern`.
  - Strict type semantics: `bool` is not `int`, `int` is not `float`,
    no implicit coercion (ADR-0003).
  - JSON Schema export for AI catalogs — one schema, two uses (runtime
    validation and tool descriptions cannot disagree).
- Plan parser:
  - Single-call form: `{"call": ..., "with": ...}`.
  - Multi-step form: `{"version": "1", "steps": [...]}`.
  - `$ref` grammar for cross-step references.
  - Forward references and cycles rejected at parse time.
  - Resource limits: `max_bytes`, `max_steps`, `max_depth`.
- Verifier: capability resolution, schema validation, reference type
  checking, dependency-graph analysis. Produces a `VerifiedPlan` (the
  only thing the executor accepts).
- `VerifiedPlan` intermediate representation: frozen, unforgeable,
  snapshot-hashed (ADR-0002).
- `logix.run(plan)`, `logix.verify(plan)`, `logix.execute(verified_plan)`.
- `Result`, `VerificationReport`, `Error`, `Trace`, `StepTrace`.
- Stable error-code taxonomy: `INVALID_PLAN`, `UNKNOWN_CAPABILITY`,
  `SCHEMA_VALIDATION_FAILED`, `INVALID_REFERENCE`, `DEPENDENCY_CYCLE`,
  `POLICY_REJECTED`, `AUTHORIZATION_FAILED`, `APPROVAL_REQUIRED`,
  `RESOURCE_LIMIT_EXCEEDED`, `HANDLER_FAILED`,
  `OUTPUT_VALIDATION_FAILED`, `EXECUTION_CANCELLED`,
  `IDEMPOTENCY_CONFLICT`, `GROUNDING_REQUIRED`.
- `logix.tools.describe()` and `logix.tools.format(provider)` — the AI
  catalog. `"json"` requires no optional package; unknown providers fall
  back to neutral.
- `ToolSpec` — provider-neutral capability description.

#### Semantic layer — experimental

- `logix.authorize(capability, check=...)` — live-state invariants in
  the recheck window. `Allow`, `Deny`, `RequireApproval` decision types.
  A crashing check fails closed.
- `logix.require_approval(capability)` — approval-gated capabilities.
  `ApprovalToken` bound to `(capability, args_hash, principal,
  context_hash)`. Application-issued via `execgate.approval.issue(...)`.
- `logix.grounding(require_ref_for=..., literal_allowlist=...)` —
  sensitive arguments must be `$ref`-sourced (ADR-0005).
- `ExecutionContext` — trusted caller identity. Frozen; `extra` is a
  `MappingProxyType`.
- `logix.audit(hook)` — safe per-step and per-result audit events.
- The recheck window (ADR-0004): verification is not authorization; live
  state is re-read before every handler invocation.
- `idempotent=True` capabilities — deduplicated by
  `(capability_name, args_hash)` via an `IdempotencyStore`. Default is
  an in-memory store; durable stores implement the protocol.
- `RepairLoop` — bounded retries with reroute refusal. After a
  `POLICY_REJECTED` / `AUTHORIZATION_FAILED` / `APPROVAL_REQUIRED`,
  subsequent plans that touch the same capability or effect class are
  refused.

#### Optional adapters — experimental

- **`execgate_pydantic`** — use Pydantic models as capability schemas.
  Requires `pydantic>=2,<3`. Detects models in direct, `Optional`,
  `list`, `dict`, and `Union` positions. `HandlerMode.MODEL` (default)
  passes model instances to handlers; `HandlerMode.VALUES` passes plain
  dicts. Pydantic output normalized to JSON-safe dicts; `$ref` traversal
  into model fields works.
- **`execgate_ai`** — provider adapters for the AI catalog. Zero runtime
  dependencies (pure data shaping). Built-in adapters: `"openai"`,
  `"anthropic"`, `"gemini"`, `"local"` (Ollama/llama.cpp/vLLM JSON
  mode). `ProviderAdapter` protocol — two methods: `format_tools` and
  `parse_proposal`. Adapters are leaf nodes (ADR-0006).
- **`execgate_mcp`** — MCP integration. Requires `fastmcp>=4,<5`.
  - **Server mode** (`LogixMCPServer`): expose ExecGate capabilities to any
    MCP client. Every call runs through the full pipeline.
  - **Proxy mode** (`LogixMCPProxy`): verify every call to an untrusted
    upstream MCP server before forwarding.

#### Documentation

- `docs/getting-started/` — 6-file path from install to a working AI
  integration (~15 minutes).
- `docs/lessons/` — 6 build-along tutorials:
  - 01: Refund workflow with grounding, invariants, approval, audit.
  - 02: Multi-tenant engines.
  - 03: Custom provider adapter.
  - 04: MCP proxy.
  - 05: Pydantic models as schemas.
  - 06: AI integration via OpenRouter (real model calls, `RepairLoop`).
- `docs/` reference:
  - `usage-model.md`, `system-design.md`, `architecture.md`,
    `api-reference.md`, `security.md`, `semantic-layer.md`,
    `plan-format.md`, `schemas.md`, `pydantic.md`, `ai-integration.md`,
    `writing-an-adapter.md`, `mcp.md`, `production-guide.md`,
    `integrations/xerj.md`.
- `docs/adr/` — 7 architecture decision records (0001–0007).
- `docs/mcp.md` documents the current limitations of MCP server mode:
  approval-required capabilities unreachable, multi-step plans not
  reachable, `context_factory` arity.

#### Testing and tooling

- Test suite covering core, semantic, security, Pydantic, adapters,
  integration, MCP, and fuzz paths.
- Security checklist enforced by `tests/security/` — each guarantee in
  `docs/security.md §3` has a matching test.
- Core suite passes with Pydantic and FastMCP uninstalled
  (`tests/pydantic/test_core_without_pydantic.py`,
  `tests/mcp/test_core_without_mcp.py`).
- `scripts/`:
  - `check_imports.py` — AST scan; core must import only stdlib.
  - `verify_wheel.py` — inspect a built wheel: `py.typed`, no dev
    directories, no unconditional runtime deps.
  - `clean.py`, `preflight.py`, `publish.py`, `release.py`.

### Changed

- Package renamed from `logix` to `logiq` before 0.1.0 (PyPI `logix` and
  `logix-ai` were taken). The class is still `Logix`. The split is
  permanent; `from execgate import Logix` is the import.

### Known limitations

Documented in the reference docs; not blockers for 0.1.0.

- **MCP server mode cannot carry approvals.** Capabilities with
  `requires_approval=True` are unreachable over MCP — `APPROVAL_REQUIRED`
  is permanent. See `docs/mcp.md §3.1`. Expose such capabilities through
  application code instead.
- **MCP server mode exposes single-call tools only.** Capabilities with
  grounding rules (`require_ref_for`) cannot be satisfied over MCP
  because grounding is multi-step. Composite capabilities are the
  recommended pattern. See `docs/mcp.md §3.2`.
- **MCP `context_factory` takes zero arguments.** Per-request principals
  from MCP auth metadata are not yet plumbed through. See
  `docs/mcp.md §3.4`.
- **`max_invocations`** on `PlanLimits` is present for forward
  compatibility but not enforced by the executor in 0.1.0.
- **`$ref` into `list[Model]`** (Pydantic) is not traversable. Documented
  in `docs/pydantic.md §4`; workaround is a `list[dict]` field.
- **`logix.dry_run` and `logix.explain`** are reserved names that raise
  `NotImplementedError`. Semantics deferred.
- **In-memory idempotency store** is single-process and non-durable.
  Applications requiring durable idempotency implement the
  `IdempotencyStore` protocol. See `docs/production-guide.md §6`.
- **Bare `dict`, bare `list`, `set`, `tuple`, `bytes`, `Decimal`,
  `datetime`, `Enum`, `TypedDict`** in annotations are rejected at
  registration. Use concrete types (`dict[str, X]`, `list[X]`) or a
  Pydantic model. See `docs/schemas.md §3`.

### Security notes

- **Never evaluates model-supplied data as code.** No `eval`, `exec`,
  or `__import__` on the plan path (ADR-0001). Enforced by AST scan in
  `tests/security/test_no_eval_exec.py`.
- **Unknown capabilities never invoke a handler.**
- **Invalid arguments never invoke a handler.**
- **Reference cycles and forward references rejected before execution.**
- **Schema validity is not authorization.** Live-state invariants run
  independently.
- **Approval is not model-settable.** Tokens are issued by application
  code, bound to the exact action.
- **Core is stdlib-only.** Zero third-party runtime dependencies.
  Enforced by `scripts/check_imports.py` and the
  `test_core_without_*` test files.
- **Adapters are leaf nodes.** `execgate_mcp`, `execgate_ai`, `execgate_pydantic`
  cannot import the verifier, executor, or IR (ADR-0006, ADR-0007).

The guarantee, precisely stated:

> A plan that fails ExecGate's required verification checks does not reach
> normal handler execution.

It does **not** claim that a model's natural-language claims are true,
that a permitted action is harmless, or that a verified handler produces
correct results. See `docs/security.md`.

### Dependencies

- Core: **none** (Python standard library only).
- Python: `>=3.11`.
- Optional:
  - `logiq[pydantic]`: `pydantic>=2,<3`.
  - `logiq[ai]`: none.
  - `logiq[mcp]`: `fastmcp>=4,<5`.

---

## Version history

| Version | Date | Notes |
|---|---|---|
| 0.1.0 | 2026-10-26 | First release |

---

## Versioning policy

- **Patch** — bug fixes, documentation, tests; no API change.
- **Minor** — new stable APIs, new experimental APIs, adapter additions.
  Breaking changes to experimental APIs are allowed with a changelog note.
- **Major** — breaking changes to stable APIs.

The "works with any AI that emits JSON" guarantee is part of the stable
contract: `execgate.tools.format("json")` and the neutral adapter may not be
removed or made conditional on an optional dependency in any 0.x or 1.x
release.

Error codes are stable. Adding a code is a minor change; renaming or
removing one is a major change.

The core guarantee — "a plan that fails verification does not reach a
handler" — will not be weakened in a minor or patch release.

# Contributing to ExecGate

ExecGate is a verification boundary. Bugs in this project can cause untrusted
input to reach trusted code, so contribution standards are stricter than
a typical Python library.

Read `docs/usage-model.md` and `docs/system-design.md` before writing
code. They define the invariants you are expected to preserve.

---

## Ground rules

1. **Core stays stdlib-only.** `src/logiq/` must import nothing outside
   the standard library. Optional behavior lives in `src/execgate_pydantic/`,
   `src/execgate_ai/`, and `src/execgate_mcp/`. Both
   `scripts/check_imports.py` and `tests/pydantic/test_core_without_pydantic.py`
   enforce this. A PR that adds a third-party import to the core is
   rejected.

2. **No `eval`, `exec`, `importlib` of model input, or attribute dispatch
   on model-supplied names.** Ever. `tests/security/test_no_eval_exec.py`
   is the guard. If you believe you need one of these, open an ADR first.
   See `docs/adr/0001-no-eval-no-exec.md`.

3. **The executor accepts only `VerifiedPlan`.** Do not add a convenience
   path that accepts a dict. The structural guarantee in
   `docs/system-design.md §11` depends on this. See
   `docs/adr/0002-verified-ir-immutability.md`.

4. **Adapters are leaf nodes.** Anything in `src/logiq_*/` (other than
   `src/logiq/`) may translate data in and out. It may not import the
   verifier, executor, or IR, or expose a `Logix` handle that bypasses
   `logix.run()` / `logix.execute()`. See
   `docs/adr/0006-adapters-never-touch-trust-boundary.md` and
   `docs/adr/0007-mcp-leaf-node-boundary.md`.

5. **Verification is not authorization.** `verify()` returns a
   `VerifiedPlan`; it does not grant permission to execute. Any change
   that lets a verified plan skip the recheck window is a security
   regression. See `docs/adr/0004-recheck-on-execute.md`.

6. **Reject rather than weaken.** If a type, annotation, or schema
   keyword cannot be faithfully represented, reject it with a clear
   error — do not fall back to `Any` or silently accept. See
   `docs/adr/0003-strict-type-semantics.md`.

---

## Development setup

```bash
git clone https://github.com/aldanedev-create/ExecGate.git
cd ExecGate
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run the full suite:

```bash
pytest
```

Run only the security boundary tests:

```bash
pytest tests/security -m security -v
```

Run the adapter conformance kit:

```bash
pytest tests/adapters -m conformance -v
```

Lint and type-check:

```bash
ruff check src tests scripts
ruff format --check src tests scripts
mypy src
```

Run the full preflight (what CI runs before a release):

```bash
python scripts/preflight.py
```

The core suite must pass with Pydantic and FastMCP **not** installed:

```bash
pip uninstall -y pydantic fastmcp
pytest tests/core tests/security
pip install -e ".[dev]"
```

If this fails, your change has coupled the core to an optional
dependency.

---

## What a change needs

Every pull request should include:

- **A test.** Behavior changes need a test that fails before and passes
  after. Use the existing files as a map.
- **A changelog entry** under `[Unreleased]` in `CHANGELOG.md`, marked
  `stable` / `experimental` / `reserved`.
- **Docs updates** if you touch a public API (`docs/api-reference.md`),
  a guarantee (`docs/system-design.md §3`), or an invariant in
  `docs/usage-model.md`.

Security-relevant changes additionally require:

- **A test in `tests/security/`.** If you add a guarantee, add the file
  that proves it. If you change one, update `docs/system-design.md §3`
  so the guarantee-to-test mapping stays accurate.
- **An ADR** under `docs/adr/` for any decision that constrains future
  changes: trust-boundary changes, new IR construction paths, new
  dynamic policy hooks, changes to what adapters may do.

**Do not open a PR that reduces coverage of `tests/security/`.** If you
believe a security test is wrong, that is a discussion for an issue
first.

---

## Commit and PR conventions

- One logical change per PR. Refactors land separately from behavior
  changes.
- Write commit messages in the imperative mood ("Add ...", "Reject ..."),
  not past tense.
- Reference the ADR or issue number where relevant.
- Squash merge is the default. Keep the squash commit message
  informative — it becomes the changelog line.
- Do not force-push a branch under review unless asked. Reviewers track
  comment positions; force-pushes lose context.

---

## Adding a new AI provider adapter

1. Read `docs/writing-an-adapter.md`.
2. Create `src/execgate_ai/providers/<name>.py` implementing
   `ProviderAdapter`. Two methods only: `format_tools` and
   `parse_proposal`. Zero SDK imports; pure data shaping.
3. Add `tests/adapters/test_<name>.py` that subclasses
   `AdapterContractMixin` and implements `make_adapter()` and
   `sample_proposal()`.
4. Register the adapter in `execgate_ai/registry.py` so
   `tools.format("<name>")` resolves. Unknown providers must still fall
   back to neutral — never raise.
5. The adapter must not import from `execgate.verifier`, `execgate.executor`,
   `execgate.ir`, or `execgate._internal`. The conformance kit checks this.

An adapter that cannot pass `tests/adapters/contract.py` is not
accepted, regardless of whether it "works" against a particular provider
today.

---

## Adding a new error code

1. Add the code to `docs/api-reference.md §14` and `logiq/errors.py`.
2. Add it to the changelog as a **minor** change.
3. Add a test that asserts it is raised in the documented situation.
4. Do not rename or remove existing codes except in a major release.

Error codes are part of the stable contract. Application code switches on
`Error.code`; changing a code breaks them.

---

## Changing the schema engine

The schema engine (`src/logiq/schemas/`) is the largest and most heavily
tested piece. Changes there have a wide blast radius.

- **New primitive or container type:** add the `Type` subclass, add it
  to `describe_unsupported`, add tests in
  `tests/core/test_schema_inference.py` and `tests/core/test_strict_types.py`.
- **New constraint:** add the class in `constraints.py`, add it to
  `SUPPORTED_CONSTRAINTS`, add tests in `tests/core/test_constraints.py`
  and update `docs/schemas.md §2`.
- **Change to strict type semantics:** this is an ADR-level change.
  Open an ADR first. See `docs/adr/0003-strict-type-semantics.md`.

If you are unsure whether a change falls into one of these categories,
ask in an issue before opening a PR.

---

## Changing the MCP integration

`src/execgate_mcp/` follows the leaf-node rule (ADR-0007). Changes there
must:

- Import only from the allowlist in `tests/mcp/test_leaf_node_boundary.py`.
- Not import from `execgate.verifier`, `execgate.executor`, `execgate.ir`, or
  `execgate._internal`.
- Pass `tests/mcp/test_leaf_node_boundary.py` and
  `tests/mcp/test_mcp_adapter_contract.py`.
- Pass `tests/mcp/test_core_without_mcp.py` when FastMCP is not
  installed.

A PR that weakens the leaf-node boundary is rejected regardless of
functionality. If the feature genuinely needs trust-boundary access, put
it in `src/logiq/` as a public method and expose it through `Logix` — do
not let `execgate_mcp` reach into the internals.

The known limitations of MCP server mode (approval, multi-step plans,
`context_factory` arity) are documented in `docs/mcp.md §3`. A PR that
implements a workaround for any of them should add an ADR that records
the decision. The current ADRs (0006, 0007) record *why* the limitations
exist; a new ADR would record *why* one of them is being resolved and
what the security implications are.

---

## Documentation contributions

Docs live in `docs/`. The structure:

- `docs/*.md` — reference. Written to be read top-to-bottom; usually
  updated when the code changes.
- `docs/adr/*.md` — architecture decisions. Written once, rarely
  changed. If a decision is superseded, add a new ADR that references
  the old one; do not edit the old one.
- `docs/getting-started/` — the 15-minute path. Should stay short and
  runnable.
- `docs/lessons/` — build-along tutorials. Should stay self-contained
  and end with working code.
- `docs/integrations/` — third-party integrations (XERJ, etc.).

Docs that don't match the code are bugs. If you find a discrepancy, the
fix is one of two things:

1. Fix the docs to match the code (usual case).
2. Fix the code to match the docs (the docs are the specification;
   they lose only when they're wrong about the intended behavior).

If you can't tell which, open an issue.

---

## Reporting security issues

**Do not open a public GitHub issue for a security problem.**

Email the maintainers at `security@logiq.dev` with:

- A description of the issue.
- Steps to reproduce, ideally a failing test.
- Your assessment of severity and exploitability.

We will acknowledge within 72 hours and coordinate disclosure after a
fix is available.

There is no bounty program. There is a commitment to fix real issues
quickly and publicly credit the reporter (unless anonymity is
requested).

The threat model — what ExecGate does and does not protect against — is in
`docs/security.md`. Read it before reporting; a claim that ExecGate "should
have caught" something may be a documented non-goal.

---

## Testing guidelines

- **Unit tests** for logic (`tests/core/`, `tests/semantic/`). Fast,
  isolated, no I/O.
- **Security tests** for guarantees (`tests/security/`). Each one maps
  to a specific guarantee in `docs/security.md §3`.
- **Conformance tests** for adapters (`tests/adapters/`,
  `tests/pydantic/`). Each adapter subclass must pass the mixin.
- **Integration tests** for cross-module behavior (`tests/integration/`).
  End-to-end flows with hand-written plans.
- **Wire-protocol tests** for MCP (`tests/mcp/test_wire_protocol.py`).
  Real in-memory transport.
- **Fuzz tests** for parsers (`tests/fuzz/`). Hypothesis-based; find
  crashes and contract violations.

Use `pytest.raises` for expected errors. Assert on `Error.code`, not
`Error.message` — the message is for humans and can change.

Use fixtures for shared setup. The `logix` fixture returns a fresh
engine; prefer it to module-level state. Tests must not depend on
execution order.

`filterwarnings = ["error"]` is set in `pyproject.toml`. Any warning
during a test fails the run. If your change introduces a warning, either
fix it or explicitly `warnings.catch_warnings()` it in the test with a
comment explaining why.

---

## Code style

- Ruff for linting and formatting. Line length 100.
- `mypy --strict` on `src/`. Tests are typed but not strict-checked.
- Public APIs need docstrings. Private helpers do not — a comment is
  usually enough.
- Prefer dataclasses over plain classes for value types. Prefer
  `@dataclass(frozen=True)` for anything that crosses a boundary.
- Do not add a dependency without an ADR. Even a "small" one. The core
  is stdlib-only; the adapters may have declared optional dependencies
  only.

Names: `logiq` (lowercase) is the package, `Logix` (capital L) is the
class. Do not rename either. The split is deliberate (PyPI `logix` is
taken by another package); `README.md` explains it.

---

## Communication

- **Issues** — bug reports, feature requests, design questions. Include
  a minimal reproduction if you can.
- **Discussions** — open-ended questions about design or usage.
- **PRs** — concrete changes. A PR that touches a security-relevant
  path should have a linked issue or ADR discussion first.

Be direct, be kind, assume good faith, and focus on the code.
Harassment or personal attacks are not tolerated.

---

## Code of conduct

Contributors are expected to:

- Treat others with respect.
- Give and receive constructive feedback graciously.
- Assume good faith in disagreement.
- Focus on what is best for the project and its users.

Unacceptable behavior:

- Harassment of any kind.
- Personal attacks or insults.
- Deliberate intimidation.
- Publishing others' private information without consent.

The maintainers may warn, remove comments, or ban contributors who
violate these expectations.

---

## Where to start

If you're looking for a first contribution:

- **Documentation.** The docs are 35 files; typos, unclear passages, and
  missing examples are easy wins. Look for `TODO` markers.
- **Examples.** `examples/` has empty files that need to be filled in
  (F1 in the handoff report).
- **Tests.** Coverage gaps in `src/execgate_ai/prompt_json_mode.py`
  (currently 0%), `src/logiq/_internal/immutability.py` (currently 47%).
- **Small fixes.** The handoff report lists F6 (test
  `prompt_json_mode`), F7 (fuzz xfail in `parse_plan`), F9 (wire-protocol
  test). All three are small.

Look for issues labeled `good first issue` or `documentation`. If there
are none, open an issue describing what you'd like to work on — the
maintainers will point you at something.

---

## License

Contributions are licensed under MIT (see `LICENSE`). By opening a PR
you agree to license your contribution under those terms.
```

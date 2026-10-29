"""Regression tests for the production-hardening fixes (idempotency scope/keys, token expiry,
audit identity, approval preview, packaging)."""
import pathlib
import time
import tomllib
from dataclasses import replace

import pytest

from execgate import ExecutionContext, Logix
from execgate import approval as approvals


def ctx(principal="p1", tenant="t1", rid=None):
    return ExecutionContext(principal=principal, tenant=tenant, roles=frozenset({"r"}), request_id=rid)


def make(**cap_kw):
    calls = []
    lx = Logix()

    @lx.capability(effects="write", idempotent=True, **cap_kw)
    def pay(order_id: int, request_id: str = "") -> int:
        """Pay."""
        calls.append(order_id)
        return len(calls)

    return lx, calls


# -- default key is scoped to tenant+principal ------------------------------------------------
def test_default_key_not_shared_across_principals():
    lx, calls = make()
    plan = {"call": "pay", "with": {"order_id": 1}}
    assert lx.run(plan, context=ctx("a", "t1")).ok
    assert lx.run(plan, context=ctx("b", "t2")).ok
    assert calls == [1, 1]  # both executed: no cross-tenant replay


def test_default_key_still_dedupes_same_caller_and_flags_replay():
    lx, calls = make()
    plan = {"call": "pay", "with": {"order_id": 1}}
    r1, r2 = lx.run(plan, context=ctx()), lx.run(plan, context=ctx())
    assert calls == [1] and not r1.replayed and r2.replayed
    assert r2.trace.steps[0].status == "replayed"


# -- caller-supplied key: legitimate repeats execute, misuse conflicts -------------------------
def test_arg_key_allows_repeated_identical_operations():
    lx, calls = make(idempotency_key="request_id")
    for rid in ("r1", "r2"):
        assert lx.run({"call": "pay", "with": {"order_id": 1, "request_id": rid}}, context=ctx()).ok
    assert calls == [1, 1]  # same args, different keys -> both executed


def test_arg_key_retry_replays_and_reuse_with_other_args_conflicts():
    lx, calls = make(idempotency_key="request_id")
    plan = {"call": "pay", "with": {"order_id": 1, "request_id": "r1"}}
    assert lx.run(plan, context=ctx()).ok
    again = lx.run(plan, context=ctx())
    assert again.ok and again.replayed and calls == [1]
    bad = lx.run({"call": "pay", "with": {"order_id": 2, "request_id": "r1"}}, context=ctx())
    assert not bad.ok and bad.errors[0].code == "IDEMPOTENCY_CONFLICT"


def test_context_request_id_mode_and_fail_closed():
    lx, calls = make(idempotency_key="context.request_id")
    plan = {"call": "pay", "with": {"order_id": 1}}
    missing = lx.run(plan, context=ctx(rid=None))
    assert not missing.ok and missing.errors[0].code == "AUTHORIZATION_FAILED" and calls == []
    assert lx.run(plan, context=ctx(rid="req-1")).ok
    assert lx.run(plan, context=ctx(rid="req-2")).ok
    assert lx.run(plan, context=ctx(rid="req-2")).replayed
    assert calls == [1, 1]


def test_idempotency_key_requires_idempotent():
    lx = Logix()
    with pytest.raises(ValueError):
        @lx.capability(idempotency_key="request_id")
        def f(request_id: str) -> int:
            """x"""
            return 1


# -- approval token expiry --------------------------------------------------------------------
def _gated(ttl):
    lx = Logix(approval_ttl=ttl)

    @lx.capability(effects="write", requires_approval=True)
    def move(amount: int) -> int:
        """Move."""
        return amount

    return lx


def _tok(age=0.0):
    t = approvals.issue(capability="move", args={"amount": 5}, context=ctx(), issuer="h")
    return replace(t, issued_at=time.time() - age)


def test_fresh_token_ok_expired_rejected_future_rejected():
    lx = _gated(60.0)
    plan = lx.verify({"call": "move", "with": {"amount": 5}}, context=ctx()).verified_plan
    assert lx.execute(plan, context=ctx(), approval=_tok(1)).ok
    old = lx.execute(plan, context=ctx(), approval=_tok(3600))
    assert not old.ok and old.errors[0].code == "APPROVAL_REQUIRED"
    assert not lx.execute(plan, context=ctx(), approval=_tok(-3600)).ok


def test_ttl_can_be_disabled():
    lx = _gated(None)
    plan = lx.verify({"call": "move", "with": {"amount": 5}}, context=ctx()).verified_plan
    assert lx.execute(plan, context=ctx(), approval=_tok(10**7)).ok


# -- audit identity ----------------------------------------------------------------------------
def test_audit_events_carry_principal_tenant_request_id():
    lx, _ = make()
    seen = []

    class H:
        def on_step(self, e): seen.append(e)
        def on_result(self, e): seen.append(e)

    lx.audit(H())
    lx.run({"call": "pay", "with": {"order_id": 1}}, context=ctx("alice", "acme", "req-9"))
    assert seen and all(e["principal"] == "alice" and e["tenant"] == "acme" and e["request_id"] == "req-9" for e in seen)


# -- approval preview + multi-step approval ----------------------------------------------------
def test_approval_requests_resolves_refs_and_multi_token_works():
    lx = Logix()
    log = []

    @lx.capability(effects="read")
    def look(order_id: int) -> dict[str, int]:
        """Look."""
        return {"id": order_id, "total": 100}

    @lx.capability(effects="write", requires_approval=True)
    def refund(order_id: int, cents: int) -> int:
        """Refund."""
        log.append((order_id, cents))
        return cents

    plan = {"version": "1", "steps": [
        {"id": "o", "call": "look", "with": {"order_id": 7}},
        {"id": "r1", "call": "refund", "with": {"order_id": {"$ref": "o.id"}, "cents": 10}},
        {"id": "r2", "call": "refund", "with": {"order_id": {"$ref": "o.id"}, "cents": 20}},
    ]}
    c = ctx()
    vp = lx.verify(plan, context=c).verified_plan
    reqs, errs = lx.approval_requests(vp, context=c)
    assert not errs and [r["arguments"] for r in reqs] == [{"order_id": 7, "cents": 10}, {"order_id": 7, "cents": 20}]
    toks = {r["step_id"]: approvals.issue(capability=r["capability"], args=r["arguments"], context=c, issuer="h") for r in reqs}
    assert lx.execute(vp, context=c, approval=toks).ok and log == [(7, 10), (7, 20)]


# -- packaging ---------------------------------------------------------------------------------
def test_all_extra_does_not_reference_foreign_package():
    data = tomllib.loads((pathlib.Path(__file__).parents[2] / "pyproject.toml").read_text())
    extras = data["project"]["optional-dependencies"]
    assert all(not d.lower().startswith("logiq") for deps in extras.values() for d in deps)

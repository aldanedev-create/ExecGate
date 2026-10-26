"""
Capability registration: decorator forms, programmatic registration,
attribute derivation, error cases, snapshot hash.

Reflects actual behavior of ``logix.capability`` and
``logix.capabilities.build_capability``.
"""

from __future__ import annotations

import pytest

from execgate.capabilities import Registry, build_capability

# ---------------------------------------------------------------------------
# Decorator forms
# ---------------------------------------------------------------------------


def test_bare_decorator_registers_and_returns_original(logix):
    def add(a: int, b: int) -> int:
        "Add."
        return a + b

    original = add
    decorated = logix.capability(add)

    assert decorated is original, "decorator must return the original function"
    assert "add" in logix.registry
    assert logix.registry.get("add").handler is original
    # Direct invocation still works (no wrapper).
    assert original(2, 3) == 5


def test_decorator_with_options(logix):
    @logix.capability(name="math.add", effects="read", requires_approval=True)
    def add(a: int, b: int) -> int:
        "Add."
        return a + b

    cap = logix.registry.get("math.add")
    assert cap.name == "math.add"
    assert cap.effects == "read"
    assert cap.requires_approval is True
    # The Python name is still "add".
    assert add.__name__ == "add"


def test_docstring_becomes_description(logix):
    @logix.capability
    def f(x: int) -> int:
        "This is the description."
        return x

    assert logix.registry.get("f").description == "This is the description."


def test_explicit_description_overrides_docstring(logix):
    @logix.capability(description="Overridden.")
    def f(x: int) -> int:
        "Original docstring."
        return x

    assert logix.registry.get("f").description == "Overridden."


# ---------------------------------------------------------------------------
# Programmatic registration
# ---------------------------------------------------------------------------


def test_register_method(logix):
    def greet(name: str) -> str:
        "Say hello."
        return f"Hello, {name}"

    returned = logix.capability.register(greet, name="customer.greet")
    assert returned is greet
    assert "customer.greet" in logix.registry


def test_get_and_names(logix):
    @logix.capability
    def a(x: int) -> int:
        return x

    @logix.capability
    def b(y: str) -> str:
        return y

    assert logix.capability.names() == ["a", "b"]
    assert logix.capability.get("a").name == "a"


def test_unregister(logix):
    @logix.capability
    def f(x: int) -> int:
        return x

    logix.capability.unregister("f")
    assert "f" not in logix.registry
    with pytest.raises(KeyError):
        logix.registry.get("f")


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_duplicate_name_rejected(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    with pytest.raises(ValueError, match="already registered"):
        logix.capability.register(add)


def test_empty_name_rejected():
    def f(x: int) -> int:
        return x

    with pytest.raises(ValueError, match="non-empty string"):
        build_capability(f, name="")


def test_invalid_effects_rejected():
    def f(x: int) -> int:
        return x

    with pytest.raises(ValueError, match="effects"):
        build_capability(f, effects="delete")  # only "read" / "write" / None


def test_async_function_rejected():
    async def f(x: int) -> int:
        return x

    with pytest.raises(TypeError, match="async"):
        build_capability(f)


def test_unbound_method_rejected():
    class C:
        def method(self, x: int) -> int:
            return x

    with pytest.raises(TypeError, match="self"):
        build_capability(C.method)


def test_variadic_args_rejected():
    def f(*args: int) -> int:
        return sum(args)

    with pytest.raises(TypeError, match="variadic"):
        build_capability(f)


def test_variadic_kwargs_rejected():
    def f(**kwargs: int) -> int:
        return sum(kwargs.values())

    with pytest.raises(TypeError, match="variadic"):
        build_capability(f)


def test_unsupported_annotation_rejected():
    def f(x: set) -> int:
        return 0

    with pytest.raises(TypeError, match="unsupported annotation"):
        build_capability(f)


def test_unannotated_parameter_rejected():
    def f(x) -> int:
        return 0

    with pytest.raises(TypeError, match="missing annotation"):
        build_capability(f)


def test_non_callable_rejected():
    with pytest.raises(TypeError, match="callable"):
        build_capability(42)


def test_class_rejected():
    class C:
        pass

    with pytest.raises(TypeError, match="class"):
        build_capability(C)


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def test_idempotent_field(logix):
    @logix.capability(idempotent=True)
    def charge(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    assert logix.registry.get("charge").idempotent is True


def test_require_approval_after_registration(logix):
    @logix.capability
    def issue_refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    assert logix.registry.get("issue_refund").requires_approval is False
    logix.require_approval(issue_refund)
    assert logix.registry.get("issue_refund").requires_approval is True


# ---------------------------------------------------------------------------
# Snapshot hash
# ---------------------------------------------------------------------------


def test_snapshot_hash_changes_on_registration():
    reg = Registry()

    def a(x: int) -> int:
        return x

    def b(y: str) -> str:
        return y

    reg.add(build_capability(a))
    h1 = reg.snapshot_hash()

    reg.add(build_capability(b))
    h2 = reg.snapshot_hash()
    assert h1 != h2

    reg.unregister("b")
    assert reg.snapshot_hash() == h1


def test_snapshot_hash_excludes_handler_implementation():
    """Two registries with identical contracts but different handler code
    hash identically — the contract is what matters, not the implementation."""
    reg_a = Registry()
    reg_b = Registry()

    def a_impl(x: int) -> int:
        return x

    def b_impl(x: int) -> int:
        return x + 100  # different implementation

    cap_a = build_capability(a_impl, name="same")
    cap_b = build_capability(b_impl, name="same")

    reg_a.add(cap_a)
    reg_b.add(cap_b)

    assert reg_a.snapshot_hash() == reg_b.snapshot_hash()

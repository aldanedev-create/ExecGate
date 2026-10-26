"""
Provider-specific adapters.

Each module implements ``logiq_ai.base.ProviderAdapter``. Adapters do
pure data shaping — no SDK imports, no API calls. The application has
the SDK; the adapter translates the catalog out and the response in.

Add a new provider by:

1. Creating ``providers/<name>.py`` with a class that implements the
   ``ProviderAdapter`` protocol.
2. Adding an entry to ``_PROVIDERS`` in ``logiq_ai/registry.py``.
3. Adding ``tests/adapters/test_<name>.py`` that subclasses
   ``AdapterContractMixin``.

Do not import provider SDKs here. Any need for an SDK belongs in the
application, not in the adapter.
"""
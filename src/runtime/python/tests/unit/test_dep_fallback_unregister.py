"""Issue #1162 LOW-6: legacy capability-based unregister must not substring-match.

The fallback path in ``_handle_dependency_change`` (only reachable with older
Rust cores whose events lack ``requesting_function``/``dep_index``) used to
remove every injector key where ``capability in key``. Keys are shaped
``{module}.{qualname}:dep_{N}`` so that was normally a no-op — and
over-matched when the capability happened to be a substring of an unrelated
tool's qualname (capability ``"date"`` vs a tool named ``get_date``).

Now the fallback maps capability → exact (func_id, dep_index) pairs via
DecoratorRegistry metadata, mirroring the registration fallback.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat


@pytest.fixture(autouse=True)
def _clean_registry():
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


def _func_id(func) -> str:
    return f"{func.__module__}.{func.__qualname__}"


async def _fallback_unregister(capability: str, injector) -> None:
    """Drive the fallback path: no requesting_function / dep_index."""
    with patch(
        "_mcp_mesh.engine.dependency_injector.get_global_injector",
        return_value=injector,
    ):
        await rust_heartbeat._handle_dependency_change(
            capability=capability,
            endpoint=None,
            function_name=None,
            agent_id=None,
            available=False,
            context={},
            requesting_function=None,
            dep_index=None,
            producer_kwargs=None,
        )


def _make_injector(dep_keys: list[str]) -> MagicMock:
    injector = MagicMock()
    injector.unregister_dependency = AsyncMock()
    # Present so the OLD substring-matching code path would have had
    # something to over-match against. The fixed code consults membership
    # via get_dependency() before unregistering, so wire it to the dict.
    injector._dependencies = {key: object() for key in dep_keys}
    injector.get_dependency = lambda name: injector._dependencies.get(name)
    return injector


class TestFallbackUnregister:
    @pytest.mark.asyncio
    async def test_capability_substring_of_qualname_does_not_over_match(self):
        """capability="date" must NOT remove deps of a tool whose qualname
        contains "date" (get_date) — only deps declared on capability="date"."""

        async def report_tool(prompt: str, date=None):
            return date

        DecoratorRegistry.register_mesh_tool(
            report_tool,
            {"capability": "report", "dependencies": [{"capability": "date"}]},
        )

        async def get_date(prompt: str, other=None):
            return other

        DecoratorRegistry.register_mesh_tool(
            get_date,
            {"capability": "get_date", "dependencies": [{"capability": "other_cap"}]},
        )

        consumer_key = f"{_func_id(report_tool)}:dep_0"
        unrelated_key = f"{_func_id(get_date)}:dep_0"
        # Sanity: the unrelated key contains the capability as a substring —
        # the exact shape the old code over-matched on.
        assert "date" in unrelated_key

        injector = _make_injector([consumer_key, unrelated_key])
        await _fallback_unregister("date", injector)

        injector.unregister_dependency.assert_awaited_once_with(consumer_key)

    @pytest.mark.asyncio
    async def test_correct_func_id_and_dep_index_removed_on_metadata_match(self):
        """Multi-dependency consumer: only the dep slot whose declared
        capability matches is unregistered, at the right index."""

        async def consumer(prompt: str, time_svc=None, date_svc=None):
            return date_svc

        DecoratorRegistry.register_mesh_tool(
            consumer,
            {
                "capability": "consumer_tool",
                "dependencies": [{"capability": "time"}, {"capability": "date"}],
            },
        )

        injector = _make_injector(
            [f"{_func_id(consumer)}:dep_0", f"{_func_id(consumer)}:dep_1"]
        )
        await _fallback_unregister("date", injector)

        injector.unregister_dependency.assert_awaited_once_with(
            f"{_func_id(consumer)}:dep_1"
        )

    @pytest.mark.asyncio
    async def test_no_matching_capability_unregisters_nothing(self):
        async def consumer(prompt: str, dep=None):
            return dep

        DecoratorRegistry.register_mesh_tool(
            consumer,
            {"capability": "consumer_tool", "dependencies": [{"capability": "time"}]},
        )

        injector = _make_injector([f"{_func_id(consumer)}:dep_0"])
        await _fallback_unregister("date", injector)

        injector.unregister_dependency.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_declared_but_unregistered_slot_is_skipped(self):
        """A slot whose declared capability matches but that was never
        registered (dependency never resolved) must not be unregistered —
        and must not produce a misleading 'Unregistered dependency' log."""

        async def consumer(prompt: str, date_svc=None):
            return date_svc

        DecoratorRegistry.register_mesh_tool(
            consumer,
            {"capability": "consumer_tool", "dependencies": [{"capability": "date"}]},
        )

        # Injector has NO registered deps — the slot is declared only.
        injector = _make_injector([])
        await _fallback_unregister("date", injector)

        injector.unregister_dependency.assert_not_awaited()

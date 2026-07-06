"""
RFC #1280 service-view facade (Python runtime, engine side).

A ``MeshServiceFacade`` is the object injected for a ``@mesh.service`` consumer
view parameter on a ``@mesh.tool``. Each method call delegates to the
per-capability proxy read from the wrapper's stable ``_mesh_injected_deps``
array AT CALL TIME — so a slot rebinding via ``update_dependency`` (topology
change) is picked up transparently.

* Unresolved OPTIONAL method → ``ToolError`` carrying the same
  ``{"error":"dependency_unavailable","capability":<cap>}`` envelope the
  #1273 pre-invoke refusal uses, naming the capability.
* ``min_available`` floor (consumer-local): when fewer than the floor of the
  view's methods resolve, EVERY facade call raises
  ``MeshServiceUnavailableError`` — settle-grace-aware (waits out the
  per-capability settle keys within the remaining budget before the
  authoritative recount), mirroring the Java runtime's ``enforceFloor``.
"""

import asyncio
import inspect
import json
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class MeshServiceFacade:
    """Injected facade for a ``@mesh.service`` consumer-view parameter."""

    def __init__(
        self,
        *,
        view_name: str,
        min_available: int,
        methods: list,
        func_id: str,
        injected_deps_array: list,
        get_dependency_fn: Callable[[str], Any | None],
    ) -> None:
        # ``methods``: list of dicts {method_name, capability, dep_index}.
        self._view_name = view_name
        self._min_available = min_available
        self._methods = methods
        self._method_by_name = {m["method_name"]: m for m in methods}
        self._func_id = func_id
        self._injected = injected_deps_array
        self._get_dep = get_dependency_fn

    # -- slot resolution ----------------------------------------------------

    def _resolve(self, dep_index: int) -> Any | None:
        """Read the live proxy for a method's slot (array first, injector
        composite-key fallback) — same lookup the injection path uses."""
        proxy = None
        if dep_index < len(self._injected):
            proxy = self._injected[dep_index]
        if proxy is None:
            proxy = self._get_dep(f"{self._func_id}:dep_{dep_index}")
        return proxy

    def _count_available(self) -> int:
        return sum(1 for m in self._methods if self._resolve(m["dep_index"]) is not None)

    # -- floor --------------------------------------------------------------

    async def _enforce_floor(self) -> None:
        if self._min_available <= 0:
            return
        from .settle import get_settle_state

        # Count FIRST — a floored view whose floor is already satisfied never
        # waits, so an unresolvable method next to enough resolved ones can
        # never park the call for the whole budget.
        available = self._count_available()
        if available >= self._min_available:
            return

        state = get_settle_state()
        # Settle-aware wait: race ALL currently-unresolved edges concurrently
        # (wake on ANY resolution, not serially per edge), recount, and loop
        # until the floor is met or the budget is spent. A serial per-edge wait
        # would burn the whole budget on one unresolvable edge before ever
        # seeing a sibling resolve.
        while (
            available < self._min_available
            and not state.is_settled()
            and state.remaining() > 0
        ):
            pending = [
                m for m in self._methods if self._resolve(m["dep_index"]) is None
            ]
            if not pending:
                break
            tasks = [
                asyncio.ensure_future(
                    state.wait_for_async(
                        f"{self._func_id}:dep_{m['dep_index']}",
                        m["capability"],
                        logger,
                    )
                )
                for m in pending
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                # Let cancellations run wait_for_async's finally cleanup.
                await asyncio.gather(*tasks, return_exceptions=True)
            available = self._count_available()

        if available < self._min_available:
            from mesh._service import MeshServiceUnavailableError

            logger.info(
                "service view %s below floor: methods_available=%d/%d (min_available=%d)",
                self._view_name,
                available,
                len(self._methods),
                self._min_available,
            )
            raise MeshServiceUnavailableError(
                self._view_name, available, len(self._methods), self._min_available
            )

    # -- delegation ---------------------------------------------------------

    def __getattr__(self, name: str):
        # __getattr__ only fires for names not found normally, so real
        # attributes/methods above are never shadowed.
        method_by_name = self.__dict__.get("_method_by_name", {})
        m = method_by_name.get(name)
        if m is None:
            raise AttributeError(
                f"'{type(self).__name__}' for view "
                f"'{self.__dict__.get('_view_name')}' has no method '{name}'"
            )

        capability = m["capability"]
        method_name = m["method_name"]
        view_name = self._view_name

        async def _call(args: Optional[dict] = None, **kwargs):
            await self._enforce_floor()
            proxy = self._resolve(m["dep_index"])
            if proxy is None:
                from fastmcp.exceptions import ToolError

                raise ToolError(
                    json.dumps(
                        {
                            "error": "dependency_unavailable",
                            "capability": capability,
                        }
                    )
                )

            # Convention: the injected mesh proxies take tool arguments as
            # KEYWORDS, not a positional dict — UnifiedMCPProxy.__call__ ignores
            # *args and sends only **kwargs upstream (as named tool params, the
            # Java/uc37 wire form), and SelfDependencyProxy accepts **kwargs
            # only. So the owner-idiom single dict arg is spread into kwargs.
            # ``headers`` (if supplied) rides in kwargs and the HTTP proxy pops
            # it, mirroring how existing consumers call injected proxies.
            call_kwargs: dict = {}
            if args is not None:
                if not isinstance(args, dict):
                    raise TypeError(
                        f"service view {view_name}.{method_name}: the positional "
                        f"argument must be a dict of tool parameters, got "
                        f"{type(args).__name__}"
                    )
                call_kwargs.update(args)
            call_kwargs.update(kwargs)

            result = proxy(**call_kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result

        _call.__name__ = name
        return _call

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        try:
            counts = f"{self._count_available()}/{len(self._methods)}"
        except Exception:
            counts = f"?/{len(self._methods)}"
        return f"MeshServiceFacade[{self._view_name}, {counts} available]"

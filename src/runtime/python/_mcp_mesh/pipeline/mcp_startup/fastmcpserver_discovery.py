import logging
from typing import Any, Callable

from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)

# Warn-once guard for convert_result post-processing failures (a FastMCP 3.x
# call-convention drift would otherwise log on every tool call). Process-wide.
_convert_result_warned: list[bool] = []


def _wrap_convert_result_for_empty_collection(orig_convert: Callable) -> Callable:
    """Wrap a FastMCP tool's ``convert_result`` so an empty list/tuple return
    serializes to a real ``"[]"`` text content block (issue #1250).

    FastMCP's ``_convert_to_content`` collapses an empty list/tuple to an
    EMPTY content array — indistinguishable on the wire from a ``None``
    return. The Java and TypeScript providers always emit a ``"[]"`` text
    block, so the Python provider is the outlier. We only intervene when the
    raw handler result is an empty list/tuple AND FastMCP produced empty
    content; the structured_content / meta FastMCP computed (e.g. the
    ``{"result": []}`` envelope + ``fastmcp.wrap_result`` marker for typed
    ``-> list[...]`` tools) is preserved verbatim.

    Untouched paths:
      * ``None`` returns → ``raw_value`` is not a list/tuple → passthrough
        (stays empty content, matching today).
      * Non-empty returns → guarded by the length check → passthrough,
        byte-identical to today.

    Hot-path hardening (this wrapper sits on EVERY patched tool call): the
    original ``convert_result`` is invoked with the exact args FastMCP passed
    (``*args``/``**kwargs``) and its result is the default return. Only the
    empty-detection / re-wrap block is guarded — if a FastMCP minor changes
    the call convention or ToolResult shape, we fall back to FastMCP's own
    result (warn once) instead of breaking every tool call.
    """

    def convert_result(*args: Any, **kwargs: Any):
        # Call the original with FastMCP's exact args OUTSIDE the guard so its
        # own errors propagate normally (never swallowed by our parity fix).
        result = orig_convert(*args, **kwargs)
        try:
            raw_value = args[0] if args else kwargs.get("raw_value")
            if (
                isinstance(raw_value, (list, tuple))
                and len(raw_value) == 0
                and not result.content
            ):
                from fastmcp.tools.tool import ToolResult
                from mcp.types import TextContent

                return ToolResult(
                    content=[TextContent(type="text", text="[]")],
                    structured_content=result.structured_content,
                    meta=result.meta,
                )
        except Exception as e:  # pragma: no cover - version-drift guard
            if not _convert_result_warned:
                _convert_result_warned.append(True)
                logger.warning(
                    "empty-collection serialization (#1250 parity): "
                    "convert_result post-processing failed (%s); falling back "
                    "to FastMCP's result. Empty list/tuple tool returns may "
                    "serialize as empty content until this is resolved "
                    "(likely a FastMCP version drift).",
                    e,
                )
        return result

    return convert_result


def _patch_tool_convert_result(tool: Any, log: logging.Logger) -> bool:
    """Install the empty-collection wrapper on a single FastMCP tool.

    Returns ``True`` when the tool was newly patched, ``False`` when it was
    already patched or could not be patched.
    """
    if getattr(tool, "_mesh_empty_result_patched", False):
        return False
    orig_convert = getattr(tool, "convert_result", None)
    if orig_convert is None:
        return False
    try:
        # FastMCP Tool is a pydantic model; bypass its __setattr__ guard.
        object.__setattr__(
            tool,
            "convert_result",
            _wrap_convert_result_for_empty_collection(orig_convert),
        )
        object.__setattr__(tool, "_mesh_empty_result_patched", True)
        return True
    except Exception as e:  # pragma: no cover - defensive
        log.debug(
            f"Could not patch empty-collection serialization for "
            f"{getattr(tool, 'key', tool)!r}: {e}"
        )
        return False


def _install_add_component_hook(local_provider: Any, log: logging.Logger) -> None:
    """Wrap ``local_provider._add_component`` so EVERY tool registered on the
    server — now or later — gets the empty-collection wrapper (issue #1250).

    ``_add_component`` is the single chokepoint through which all tool
    registration flows (``server.tool`` / ``add_tool`` → ``_add_component``),
    so hooking it covers tools registered AFTER discovery runs — most
    notably the jobs-helper tools (``JobsHelperToolsStep`` runs later in the
    pipeline) and any future dynamic registration. Idempotent.
    """
    if getattr(local_provider, "_mesh_empty_result_hook_installed", False):
        return
    orig_add = getattr(local_provider, "_add_component", None)
    if orig_add is None:
        return

    def _add_component(component: Any):
        result = orig_add(component)
        try:
            key = getattr(result, "key", "") or ""
            if str(key).startswith("tool:"):
                _patch_tool_convert_result(result, log)
        except Exception as e:  # pragma: no cover - defensive
            log.debug(f"empty-collection add_component hook: {e}")
        return result

    try:
        object.__setattr__(local_provider, "_add_component", _add_component)
        object.__setattr__(local_provider, "_mesh_empty_result_hook_installed", True)
    except Exception as e:  # pragma: no cover - defensive
        log.debug(f"Could not install empty-collection add_component hook: {e}")


def patch_empty_collection_serialization(
    server_instance: Any, log: logging.Logger | None = None
) -> int:
    """Ensure empty list/tuple tool returns reach the wire as a ``"[]"`` text
    block on ``server_instance`` (issue #1250), for ALL tools past and future.

    Two-pronged and idempotent:
      1. Patch every already-registered ``tool:`` component eagerly.
      2. Hook ``_add_component`` so tools registered later (jobs-helper tools,
         dynamic registrations) are patched at registration time.

    Scoped to ``tool:`` components, so ``@mesh.route`` SSE/streaming handlers
    (FastAPI routes, not FastMCP tools) are never touched. Returns the number
    of tools newly patched in step 1. Soft-fails loudly: if the server
    exposes tools but none could be patched, logs a warning naming the
    consequence (parity fix inactive).
    """
    log = log or logger
    local_provider = getattr(server_instance, "local_provider", None)
    if local_provider is None:
        return 0

    # Cover future registrations first so a race between here and the eager
    # sweep can't leave a just-added tool unpatched.
    _install_add_component_hook(local_provider, log)

    components = getattr(local_provider, "_components", None)
    if not isinstance(components, dict):
        log.warning(
            "empty-collection serialization (#1250 parity): FastMCP "
            "local_provider._components is unavailable or not a dict (got %s); "
            "the parity fix is INACTIVE for this server — empty list/tuple "
            "tool returns will serialize as empty content.",
            type(components).__name__,
        )
        return 0

    tool_keys = [k for k in components if str(k).startswith("tool:")]
    newly = 0
    for key in tool_keys:
        if _patch_tool_convert_result(components[key], log):
            newly += 1

    marked = sum(
        1
        for k in tool_keys
        if getattr(components[k], "_mesh_empty_result_patched", False)
    )
    if tool_keys and marked == 0:
        log.warning(
            "empty-collection serialization (#1250 parity): server exposes "
            "%d tool(s) but none could be patched (FastMCP internals may have "
            "changed); the parity fix is INACTIVE — empty list/tuple tool "
            "returns will serialize as empty content.",
            len(tool_keys),
        )
    return newly


class FastMCPServerDiscoveryStep(PipelineStep):
    """
    Discovers user's FastMCP server instances and prepares for takeover.

    This step searches the global namespace for FastMCP instances,
    extracts their registered functions, and prepares for server startup.
    """

    def __init__(self):
        super().__init__(
            name="fastmcp-server-discovery",
            required=False,  # Optional - may not have FastMCP instances
            description="Discover FastMCP server instances and prepare for takeover",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Discover FastMCP servers."""
        self.logger.debug("Discovering FastMCP server instances...")

        result = PipelineResult(message="FastMCP server discovery completed")

        try:
            # Discover FastMCP instances from the main module
            discovered_servers = self._discover_fastmcp_instances()

            if not discovered_servers:
                result.status = PipelineStatus.SKIPPED
                result.message = "No FastMCP server instances found"
                self.logger.info("⚠️ No FastMCP instances discovered")
                return result

            # Empty-collection serialization parity (#1250): ensure an empty
            # list/tuple tool return reaches the wire as a real "[]" text block
            # instead of empty content, matching the Java/TS providers.
            for server_name, server_instance in list(discovered_servers.items()):
                patched = patch_empty_collection_serialization(
                    server_instance, self.logger
                )
                if patched:
                    self.logger.debug(
                        f"🩹 Patched {patched} tool(s) on '{server_name}' for "
                        f"empty-collection serialization parity (#1250)"
                    )

            # Extract server information
            server_info = []
            total_registered_functions = 0

            for server_name, server_instance in list(discovered_servers.items()):
                info = self._extract_server_info(server_name, server_instance)
                server_info.append(info)
                total_registered_functions += info.get("function_count", 0)

                self.logger.debug(
                    f"📡 Discovered FastMCP server '{server_name}': "
                    f"{info.get('function_count', 0)} functions"
                )

            # Store in context for subsequent steps
            result.add_context("fastmcp_servers", discovered_servers)
            result.add_context("fastmcp_server_info", server_info)
            result.add_context("fastmcp_server_count", len(discovered_servers))
            result.add_context("fastmcp_total_functions", total_registered_functions)

            # Store server info in DecoratorRegistry for heartbeat schema extraction (Phase 2)
            from ...engine.decorator_registry import DecoratorRegistry

            # Convert server_info list to dict for easier lookup
            server_info_dict = {info["server_name"]: info for info in server_info}
            DecoratorRegistry.store_fastmcp_server_info(server_info_dict)

            result.message = (
                f"Discovered {len(discovered_servers)} FastMCP servers "
                f"with {total_registered_functions} total functions"
            )

            self.logger.info(
                f"🎯 FastMCP discovery complete: {len(discovered_servers)} servers, "
                f"{total_registered_functions} functions"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"FastMCP server discovery failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ FastMCP server discovery failed: {e}")

        return result

    def _discover_fastmcp_instances(self) -> dict[str, Any]:
        """
        Discover FastMCP instances in the global namespace.

        This looks in multiple modules for FastMCP instances.
        """
        discovered = {}

        try:
            import sys

            # First check the main module
            main_module = sys.modules.get("__main__")
            if main_module:
                discovered.update(
                    self._search_module_for_fastmcp(main_module, "__main__")
                )

            # Also search recently imported modules that might contain FastMCP instances
            # Look for modules that were likely user modules (not built-ins)
            # Exclude common system/library modules but include all user modules
            system_modules = {
                "sys",
                "os",
                "logging",
                "asyncio",
                "json",
                "datetime",
                "time",
                "threading",
                "functools",
                "inspect",
                "collections",
                "typing",
                "uuid",
                "weakref",
                "signal",
                "atexit",
                "gc",
                "warnings",
                "importlib",
                "pkgutil",
            }

            for module_name, module in list(sys.modules.items()):
                if (
                    module
                    and not module_name.startswith("_")
                    and module_name not in system_modules
                    and not module_name.startswith("mcp_mesh")  # Skip our own modules
                    and not module_name.startswith("mesh")  # Skip our own modules
                    and not module_name.startswith(
                        "fastmcp."
                    )  # Skip FastMCP library modules
                    and not module_name.startswith("mcp.")  # Skip MCP library modules
                    and hasattr(module, "__file__")
                    and module.__file__
                    and not module.__file__.endswith(".so")
                ):  # Skip binary extensions

                    found_in_module = self._search_module_for_fastmcp(
                        module, module_name
                    )
                    if found_in_module:
                        self.logger.debug(
                            f"Found {len(found_in_module)} FastMCP instances in module {module_name}"
                        )
                        discovered.update(found_in_module)

            self.logger.debug(
                f"FastMCP discovery complete: {len(discovered)} instances found"
            )
            return discovered

        except Exception as e:
            self.logger.error(f"Error discovering FastMCP instances: {e}")
            return discovered

    def _search_module_for_fastmcp(
        self, module: Any, module_name: str
    ) -> dict[str, Any]:
        """Search a specific module for FastMCP instances."""
        found = {}

        try:
            if not hasattr(module, "__dict__"):
                return found

            module_globals = vars(module)
            # Only log if we find FastMCP instances to reduce noise

            for var_name, var_value in list(module_globals.items()):
                if self._is_fastmcp_instance(var_value):
                    instance_key = f"{module_name}.{var_name}"
                    found[instance_key] = var_value
                    self.logger.debug(
                        f"✅ Found FastMCP instance: {instance_key} = {var_value}"
                    )
                elif hasattr(var_value, "__class__") and "FastMCP" in str(
                    type(var_value)
                ):
                    self.logger.debug(
                        f"🔍 Potential FastMCP-like object in {module_name}: {var_name} = {var_value}"
                    )

        except Exception as e:
            self.logger.debug(f"Error searching module {module_name}: {e}")

        return found

    def _is_fastmcp_instance(self, obj: Any) -> bool:
        """Check if an object is a FastMCP server instance."""
        try:
            # Check if it's a FastMCP instance by looking at class name and attributes
            if hasattr(obj, "__class__"):
                class_name = obj.__class__.__name__
                if class_name == "FastMCP":
                    # Verify it has the expected FastMCP attributes
                    return (
                        hasattr(obj, "name")
                        and hasattr(obj, "local_provider")
                        and hasattr(obj, "tool")  # The decorator method
                    )
            return False
        except Exception:
            return False

    def _extract_server_info(
        self, server_name: str, server_instance: Any
    ) -> dict[str, Any]:
        """Extract detailed information from a FastMCP server instance."""
        info = {
            "server_name": server_name,
            "server_instance": server_instance,
            "fastmcp_name": getattr(server_instance, "name", "unknown"),
            "function_count": 0,
            "tools": {},
            "prompts": {},
            "resources": {},
            "tool_manager": None,
        }

        try:
            local_provider = getattr(server_instance, "local_provider", None)
            if local_provider is None:
                self.logger.warning(f"Server '{server_name}' has no local_provider")
                return info

            # v3: Components stored in local_provider._components dict
            # Keys format: "tool:name@", "prompt:name@", "resource:uri@"
            components = getattr(local_provider, "_components", {})

            tools = {}
            prompts = {}
            resources = {}

            for comp_key, comp_obj in components.items():
                if comp_key.startswith("tool:"):
                    tool_name = getattr(comp_obj, "name", comp_key)
                    tools[tool_name] = comp_obj
                elif comp_key.startswith("prompt:"):
                    prompt_name = getattr(comp_obj, "name", comp_key)
                    prompts[prompt_name] = comp_obj
                elif comp_key.startswith("resource:"):
                    resource_name = getattr(comp_obj, "name", comp_key)
                    resources[resource_name] = comp_obj

            info["tools"] = tools
            info["prompts"] = prompts
            info["resources"] = resources
            info["function_count"] = len(tools) + len(prompts) + len(resources)

            # Log tools
            self.logger.debug(f"Server '{server_name}' has {len(tools)} tools:")
            for tool_name, tool in tools.items():
                function_ptr = getattr(tool, "fn", None)
                self.logger.debug(f"  - {tool_name}: {function_ptr}")

            if prompts:
                self.logger.debug(f"Server '{server_name}' has {len(prompts)} prompts")

            if resources:
                self.logger.debug(
                    f"Server '{server_name}' has {len(resources)} resources"
                )

        except Exception as e:
            self.logger.error(f"Error extracting server info for '{server_name}': {e}")

        return info

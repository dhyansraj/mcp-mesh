import gc
import inspect
import logging
from typing import Any, Dict, List, Optional

from ..shared import PipelineResult, PipelineStatus, PipelineStep


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
                        and hasattr(obj, "_tool_manager")
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
            # Extract tool manager
            if hasattr(server_instance, "_tool_manager"):
                tool_manager = server_instance._tool_manager
                info["tool_manager"] = tool_manager

                # Extract registered tools
                if hasattr(tool_manager, "_tools"):
                    tools = tool_manager._tools
                    info["tools"] = tools
                    info["function_count"] += len(tools)

                    self.logger.debug(f"Server '{server_name}' has {len(tools)} tools:")
                    for tool_name, tool in list(tools.items()):
                        function_ptr = getattr(tool, "fn", None)
                        self.logger.debug(f"  - {tool_name}: {function_ptr}")

            # Extract prompts if available
            if hasattr(server_instance, "_prompt_manager"):
                prompt_manager = server_instance._prompt_manager
                if hasattr(prompt_manager, "_prompts"):
                    prompts = prompt_manager._prompts
                    info["prompts"] = prompts
                    info["function_count"] += len(prompts)

                    self.logger.debug(
                        f"Server '{server_name}' has {len(prompts)} prompts"
                    )

            # Extract resources if available
            if hasattr(server_instance, "_resource_manager"):
                resource_manager = server_instance._resource_manager
                if hasattr(resource_manager, "_resources"):
                    resources = resource_manager._resources
                    info["resources"] = resources
                    info["function_count"] += len(resources)

                    self.logger.debug(
                        f"Server '{server_name}' has {len(resources)} resources"
                    )

        except Exception as e:
            self.logger.error(f"Error extracting server info for '{server_name}': {e}")

        return info

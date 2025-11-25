"""
Dependency resolution step for MCP Mesh pipeline.

Handles processing dependency resolution from registry response and
updating the dependency injection system.
"""

import json
import logging
from typing import Any

from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)

# Global state for dependency hash tracking across heartbeat cycles
_last_dependency_hash = None


class DependencyResolutionStep(PipelineStep):
    """
    Processes dependency resolution from registry response.

    Takes the dependencies_resolved data from the heartbeat response
    and prepares it for dependency injection (simplified for now).
    """

    def __init__(self):
        super().__init__(
            name="dependency-resolution",
            required=False,  # Optional - can work without dependencies
            description="Process dependency resolution from registry",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Process dependency resolution with hash-based change detection."""
        self.logger.debug("Processing dependency resolution...")

        result = PipelineResult(message="Dependency resolution processed")

        try:
            # Get heartbeat response and registry wrapper
            heartbeat_response = context.get("heartbeat_response", {})
            registry_wrapper = context.get("registry_wrapper")

            if not heartbeat_response or not registry_wrapper:
                result.status = PipelineStatus.SUCCESS
                result.message = (
                    "No heartbeat response or registry wrapper - completed successfully"
                )
                self.logger.info("ℹ️ No heartbeat response to process - this is normal")
                return result

            # Use the existing hash-based change detection and rewiring logic
            await self.process_heartbeat_response_for_rewiring(heartbeat_response)

            # For context consistency, also extract dependency count
            dependencies_resolved = registry_wrapper.parse_tool_dependencies(
                heartbeat_response
            )
            dependency_count = sum(
                len(deps) if isinstance(deps, list) else 0
                for deps in dependencies_resolved.values()
            )

            # Store processed dependencies info for context
            result.add_context("dependency_count", dependency_count)
            result.add_context("dependencies_resolved", dependencies_resolved)

            result.message = "Dependency resolution completed (efficient hash-based)"
            self.logger.debug(
                "🔗 Dependency resolution step completed using hash-based change detection"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Dependency resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Dependency resolution failed: {e}")

        return result

    def _extract_dependency_state(
        self, heartbeat_response: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """Extract dependency state structure from heartbeat response.

        Preserves array structure and order from registry to support multiple
        dependencies with the same capability name (e.g., different versions/tags).

        Returns:
            {function_name: [{capability, endpoint, function_name, status, agent_id, kwargs}, ...]}
        """
        state = {}
        dependencies_resolved = heartbeat_response.get("dependencies_resolved", {})

        for function_name, dependency_list in dependencies_resolved.items():
            if not isinstance(dependency_list, list):
                continue

            state[function_name] = []
            for dep_resolution in dependency_list:
                if (
                    not isinstance(dep_resolution, dict)
                    or "capability" not in dep_resolution
                ):
                    continue

                # Preserve array structure to maintain order and support duplicate capabilities
                state[function_name].append(
                    {
                        "capability": dep_resolution["capability"],
                        "endpoint": dep_resolution.get("endpoint", ""),
                        "function_name": dep_resolution.get("function_name", ""),
                        "status": dep_resolution.get("status", ""),
                        "agent_id": dep_resolution.get("agent_id", ""),
                        "kwargs": dep_resolution.get("kwargs", {}),
                    }
                )

        return state

    def _hash_dependency_state(self, state: dict) -> str:
        """Create hash of dependency state structure."""
        import hashlib

        # Convert to sorted JSON string for consistent hashing
        state_json = json.dumps(state, sort_keys=True)
        return hashlib.sha256(state_json.encode()).hexdigest()[
            :16
        ]  # First 16 chars for readability

    async def process_heartbeat_response_for_rewiring(
        self, heartbeat_response: dict[str, Any]
    ) -> None:
        """Process heartbeat response to update existing dependency injection.

        Uses hash-based comparison to efficiently detect when ANY dependency changes
        and then updates ALL affected functions in one operation.

        Resilience logic:
        - No response (connection error, 5xx) → Skip entirely (keep existing wiring)
        - 2xx response with empty dependencies → Unwire all dependencies
        - 2xx response with partial dependencies → Update to match registry exactly
        """
        try:
            if not heartbeat_response:
                # No response from registry (connection error, timeout, 5xx)
                # → Skip entirely for resilience (keep existing dependencies)
                self.logger.debug(
                    "No heartbeat response - skipping rewiring for resilience"
                )
                return

            # Extract current dependency state structure
            current_state = self._extract_dependency_state(heartbeat_response)

            # IMPORTANT: Empty state from successful response means "unwire everything"
            # This is different from "no response" which means "keep existing for resilience"

            # Hash the current state (including empty state)
            current_hash = self._hash_dependency_state(current_state)

            # Compare with previous state (use global variable)
            global _last_dependency_hash
            if current_hash == _last_dependency_hash:
                self.logger.debug(
                    f"🔄 Dependency state unchanged (hash: {current_hash}), skipping rewiring"
                )
                return

            # State changed - determine what changed
            function_count = len(current_state)
            total_deps = sum(len(deps) for deps in current_state.values())

            if _last_dependency_hash is None:
                if function_count > 0:
                    self.logger.info(
                        f"🔄 Initial dependency state detected: {function_count} functions, {total_deps} dependencies"
                    )
                else:
                    self.logger.info(
                        "🔄 Initial dependency state detected: no dependencies"
                    )
            else:
                self.logger.info(
                    f"🔄 Dependency state changed (hash: {_last_dependency_hash} → {current_hash})"
                )
                if function_count > 0:
                    self.logger.info(
                        f"🔄 Updating dependencies for {function_count} functions ({total_deps} total dependencies)"
                    )
                else:
                    self.logger.info(
                        "🔄 Registry reports no dependencies - unwiring all existing dependencies"
                    )

            # Import here to avoid circular imports
            from ...engine.dependency_injector import get_global_injector
            from ...engine.unified_mcp_proxy import EnhancedUnifiedMCPProxy

            injector = get_global_injector()

            # Step 1: Collect all dependency keys (func_id:dep_index) that should exist
            # Map tool names to func_ids first
            from ...engine.decorator_registry import DecoratorRegistry

            tool_name_to_func_id = {}
            mesh_tools = DecoratorRegistry.get_mesh_tools()
            for tool_name, decorated_func in mesh_tools.items():
                func = decorated_func.function
                func_id = f"{func.__module__}.{func.__qualname__}"
                tool_name_to_func_id[tool_name] = func_id

            target_dependency_keys = set()
            for function_name, dependency_list in current_state.items():
                # Map tool name to func_id
                func_id = tool_name_to_func_id.get(function_name, function_name)
                for dep_index in range(len(dependency_list)):
                    dep_key = f"{func_id}:dep_{dep_index}"
                    target_dependency_keys.add(dep_key)

            # Step 2: Find existing dependency keys that need to be removed (unwired)
            # This handles the case where registry stops reporting some dependencies
            existing_dependency_keys = (
                set(injector._dependencies.keys())
                if hasattr(injector, "_dependencies")
                else set()
            )
            keys_to_remove = existing_dependency_keys - target_dependency_keys

            unwired_count = 0
            for dep_key in keys_to_remove:
                await injector.unregister_dependency(dep_key)
                unwired_count += 1
                self.logger.info(
                    f"🗑️ Unwired dependency '{dep_key}' (no longer reported by registry)"
                )

            # Step 3: Apply all dependency updates using positional indexing
            updated_count = 0
            for function_name, dependency_list in current_state.items():
                # Map tool name to func_id (using mapping from Step 1)
                func_id = tool_name_to_func_id.get(function_name, function_name)

                for dep_index, dep_info in enumerate(dependency_list):
                    status = dep_info["status"]
                    endpoint = dep_info["endpoint"]
                    dep_function_name = dep_info["function_name"]
                    capability = dep_info["capability"]
                    kwargs_config = dep_info.get("kwargs", {})

                    if status == "available" and endpoint and dep_function_name:
                        # Import here to avoid circular imports
                        # Get current agent ID for self-dependency detection
                        import os

                        from ...engine.self_dependency_proxy import \
                            SelfDependencyProxy

                        # Get current agent ID from DecoratorRegistry (single source of truth)
                        current_agent_id = None
                        try:
                            from ...engine.decorator_registry import \
                                DecoratorRegistry

                            config = DecoratorRegistry.get_resolved_agent_config()
                            current_agent_id = config["agent_id"]
                            self.logger.debug(
                                f"🔍 Current agent ID from DecoratorRegistry: '{current_agent_id}'"
                            )
                        except Exception as e:
                            # Fallback to environment variable
                            current_agent_id = os.getenv("MCP_MESH_AGENT_ID")
                            self.logger.debug(
                                f"🔍 Current agent ID from environment: '{current_agent_id}' (fallback due to: {e})"
                            )

                        target_agent_id = dep_info.get("agent_id")
                        self.logger.debug(
                            f"🔍 Target agent ID from registry: '{target_agent_id}'"
                        )

                        # Determine if this is a self-dependency
                        is_self_dependency = (
                            current_agent_id
                            and target_agent_id
                            and current_agent_id == target_agent_id
                        )

                        self.logger.debug(
                            f"🔍 Self-dependency check for '{capability}': "
                            f"current='{current_agent_id}' vs target='{target_agent_id}' "
                            f"→ {'SELF' if is_self_dependency else 'CROSS'}-dependency"
                        )

                        if is_self_dependency:
                            # Create self-dependency proxy with WRAPPER function (not original)
                            # The wrapper has dependency injection logic, so calling it ensures
                            # the target function's dependencies are also injected properly.
                            wrapper_func = None
                            if dep_function_name in mesh_tools:
                                wrapper_func = mesh_tools[dep_function_name].function
                                self.logger.debug(
                                    f"🔍 Found wrapper for '{dep_function_name}' in DecoratorRegistry"
                                )

                            if wrapper_func:
                                new_proxy = SelfDependencyProxy(
                                    wrapper_func, dep_function_name
                                )
                                self.logger.info(
                                    f"🔄 SELF-DEPENDENCY: Using wrapper for '{capability}' "
                                    f"(local call with full DI support)"
                                )
                            else:
                                # Fallback to original function if wrapper not found
                                original_func = injector.find_original_function(
                                    dep_function_name
                                )
                                if original_func:
                                    new_proxy = SelfDependencyProxy(
                                        original_func, dep_function_name
                                    )
                                    self.logger.warning(
                                        f"⚠️ SELF-DEPENDENCY: Using original function for '{capability}' "
                                        f"(wrapper not found, DI may not work for nested deps)"
                                    )
                                else:
                                    self.logger.error(
                                        f"❌ Cannot create SelfDependencyProxy for '{capability}': "
                                        f"neither wrapper nor original function '{dep_function_name}' found, falling back to HTTP"
                                    )
                                    # Use unified proxy for fallback
                                    new_proxy = EnhancedUnifiedMCPProxy(
                                        endpoint,
                                        dep_function_name,
                                        kwargs_config=kwargs_config,
                                    )
                                    self.logger.debug(
                                        f"🔧 Created EnhancedUnifiedMCPProxy (fallback): {kwargs_config}"
                                    )
                        else:
                            # Create cross-service proxy using unified proxy
                            new_proxy = EnhancedUnifiedMCPProxy(
                                endpoint,
                                dep_function_name,
                                kwargs_config=kwargs_config,
                            )
                            self.logger.info(
                                f"🔄 Updated to EnhancedUnifiedMCPProxy: '{capability}' -> {endpoint}/{dep_function_name}, "
                                f"timeout={kwargs_config.get('timeout', 30)}s, streaming={kwargs_config.get('streaming', False)}"
                            )

                        # Register with composite key using func_id (not tool name) to match injector lookup
                        dep_key = f"{func_id}:dep_{dep_index}"
                        await injector.register_dependency(dep_key, new_proxy)
                        updated_count += 1
                        self.logger.debug(
                            f"🔗 Registered dependency '{capability}' at position {dep_index} with key '{dep_key}' (func_id: {func_id})"
                        )
                    else:
                        if status != "available":
                            self.logger.debug(
                                f"⚠️ Dependency '{capability}' at position {dep_index} not available: {status}"
                            )
                        else:
                            self.logger.warning(
                                f"⚠️ Cannot update dependency '{capability}' at position {dep_index}: missing endpoint or function_name"
                            )

            # Store new hash for next comparison (use global variable)
            _last_dependency_hash = current_hash

            if unwired_count > 0 and updated_count > 0:
                self.logger.info(
                    f"✅ Successfully unwired {unwired_count} and updated {updated_count} dependencies (state hash: {current_hash})"
                )
            elif unwired_count > 0:
                self.logger.info(
                    f"✅ Successfully unwired {unwired_count} dependencies (state hash: {current_hash})"
                )
            elif updated_count > 0:
                self.logger.info(
                    f"✅ Successfully updated {updated_count} dependencies (state hash: {current_hash})"
                )
            else:
                self.logger.info(
                    f"✅ Dependency state synchronized (state hash: {current_hash})"
                )

        except Exception as e:
            self.logger.error(
                f"❌ Failed to process heartbeat response for rewiring: {e}"
            )
            # Don't raise - this should not break the heartbeat loop

    # Proxy type determination method removed - now using unified proxy for all dependencies

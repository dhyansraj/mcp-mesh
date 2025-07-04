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
    ) -> dict[str, dict[str, dict[str, str]]]:
        """Extract dependency state structure from heartbeat response.

        Returns:
            {function_name: {capability: {endpoint, function_name, status}}}
        """
        state = {}
        dependencies_resolved = heartbeat_response.get("dependencies_resolved", {})

        for function_name, dependency_list in dependencies_resolved.items():
            if not isinstance(dependency_list, list):
                continue

            state[function_name] = {}
            for dep_resolution in dependency_list:
                if (
                    not isinstance(dep_resolution, dict)
                    or "capability" not in dep_resolution
                ):
                    continue

                capability = dep_resolution["capability"]
                state[function_name][capability] = {
                    "endpoint": dep_resolution.get("endpoint", ""),
                    "function_name": dep_resolution.get("function_name", ""),
                    "status": dep_resolution.get("status", ""),
                    "agent_id": dep_resolution.get("agent_id", ""),
                }

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
            from ...engine.full_mcp_proxy import EnhancedFullMCPProxy, FullMCPProxy
            from ...engine.mcp_client_proxy import (
                EnhancedMCPClientProxy,
                MCPClientProxy,
            )

            injector = get_global_injector()

            # Step 1: Collect all capabilities that should exist according to registry
            target_capabilities = set()
            for function_name, dependencies in current_state.items():
                for capability in dependencies.keys():
                    target_capabilities.add(capability)

            # Step 2: Find existing capabilities that need to be removed (unwired)
            # This handles the case where registry stops reporting some dependencies
            existing_capabilities = (
                set(injector._dependencies.keys())
                if hasattr(injector, "_dependencies")
                else set()
            )
            capabilities_to_remove = existing_capabilities - target_capabilities

            unwired_count = 0
            for capability in capabilities_to_remove:
                await injector.unregister_dependency(capability)
                unwired_count += 1
                self.logger.info(
                    f"🗑️ Unwired dependency '{capability}' (no longer reported by registry)"
                )

            # Step 3: Apply all dependency updates for capabilities that should exist
            updated_count = 0
            for function_name, dependencies in current_state.items():
                for capability, dep_info in dependencies.items():
                    status = dep_info["status"]
                    endpoint = dep_info["endpoint"]
                    dep_function_name = dep_info["function_name"]
                    kwargs_config = dep_info.get("kwargs", {})  # NEW: Extract kwargs

                    if status == "available" and endpoint and dep_function_name:
                        # Import here to avoid circular imports
                        # Get current agent ID for self-dependency detection
                        import os

                        from ...engine.full_mcp_proxy import (
                            EnhancedFullMCPProxy,
                            FullMCPProxy,
                        )
                        from ...engine.mcp_client_proxy import (
                            EnhancedMCPClientProxy,
                            MCPClientProxy,
                        )
                        from ...engine.self_dependency_proxy import SelfDependencyProxy

                        # Get current agent ID from DecoratorRegistry (single source of truth)
                        current_agent_id = None
                        try:
                            from ...engine.decorator_registry import DecoratorRegistry

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
                            # Create self-dependency proxy with cached function reference
                            original_func = injector.find_original_function(
                                dep_function_name
                            )
                            if original_func:
                                new_proxy = SelfDependencyProxy(
                                    original_func, dep_function_name
                                )
                                self.logger.warning(
                                    f"⚠️ SELF-DEPENDENCY: Using direct function call for '{capability}' "
                                    f"instead of HTTP to avoid deadlock. Consider refactoring to "
                                    f"eliminate self-dependencies if possible."
                                )
                                self.logger.info(
                                    f"🔄 Updated to SelfDependencyProxy: '{capability}'"
                                )
                            else:
                                self.logger.error(
                                    f"❌ Cannot create SelfDependencyProxy for '{capability}': "
                                    f"original function '{dep_function_name}' not found, falling back to HTTP"
                                )
                                # Use type-based proxy selection for fallback too
                                proxy_type = self._determine_proxy_type_for_capability(
                                    capability, injector
                                )
                                if proxy_type == "FullMCPProxy":
                                    # Use enhanced proxy if kwargs available
                                    if kwargs_config:
                                        new_proxy = EnhancedFullMCPProxy(
                                            endpoint,
                                            dep_function_name,
                                            kwargs_config=kwargs_config,
                                        )
                                        self.logger.debug(
                                            f"🔧 Created EnhancedFullMCPProxy with kwargs: {kwargs_config}"
                                        )
                                    else:
                                        new_proxy = FullMCPProxy(
                                            endpoint,
                                            dep_function_name,
                                            kwargs_config=kwargs_config,
                                        )
                                        self.logger.debug(
                                            "🔧 Created FullMCPProxy (no kwargs)"
                                        )
                                else:
                                    # Use enhanced proxy if kwargs available
                                    if kwargs_config:
                                        new_proxy = EnhancedMCPClientProxy(
                                            endpoint,
                                            dep_function_name,
                                            kwargs_config=kwargs_config,
                                        )
                                        self.logger.debug(
                                            f"🔧 Created EnhancedMCPClientProxy with kwargs: {kwargs_config}"
                                        )
                                    else:
                                        new_proxy = MCPClientProxy(
                                            endpoint,
                                            dep_function_name,
                                            kwargs_config=kwargs_config,
                                        )
                                        self.logger.debug(
                                            "🔧 Created MCPClientProxy (no kwargs)"
                                        )
                        else:
                            # Create cross-service proxy based on parameter types that use this capability
                            proxy_type = self._determine_proxy_type_for_capability(
                                capability, injector
                            )

                            if proxy_type == "FullMCPProxy":
                                # Use enhanced proxy if kwargs available
                                if kwargs_config:
                                    new_proxy = EnhancedFullMCPProxy(
                                        endpoint,
                                        dep_function_name,
                                        kwargs_config=kwargs_config,
                                    )
                                    self.logger.info(
                                        f"🔄 Updated to EnhancedFullMCPProxy: '{capability}' -> {endpoint}/{dep_function_name}, "
                                        f"timeout={kwargs_config.get('timeout', 30)}s, streaming={kwargs_config.get('streaming', False)}"
                                    )
                                else:
                                    new_proxy = FullMCPProxy(
                                        endpoint,
                                        dep_function_name,
                                        kwargs_config=kwargs_config,
                                    )
                                    self.logger.debug(
                                        f"🔄 Updated to FullMCPProxy: '{capability}' -> {endpoint}/{dep_function_name}"
                                    )
                            else:
                                # Use enhanced proxy if kwargs available
                                if kwargs_config:
                                    new_proxy = EnhancedMCPClientProxy(
                                        endpoint,
                                        dep_function_name,
                                        kwargs_config=kwargs_config,
                                    )
                                    self.logger.info(
                                        f"🔄 Updated to EnhancedMCPClientProxy: '{capability}' -> {endpoint}/{dep_function_name}, "
                                        f"timeout={kwargs_config.get('timeout', 30)}s, retries={kwargs_config.get('retry_count', 1)}"
                                    )
                                else:
                                    new_proxy = MCPClientProxy(
                                        endpoint,
                                        dep_function_name,
                                        kwargs_config=kwargs_config,
                                    )
                                    self.logger.debug(
                                        f"🔄 Updated to MCPClientProxy: '{capability}' -> {endpoint}/{dep_function_name}"
                                    )

                        # Update in injector (this will update ALL functions that depend on this capability)
                        await injector.register_dependency(capability, new_proxy)
                        updated_count += 1
                    else:
                        if status != "available":
                            self.logger.debug(
                                f"⚠️ Dependency '{capability}' not available: {status}"
                            )
                        else:
                            self.logger.warning(
                                f"⚠️ Cannot update dependency '{capability}': missing endpoint or function_name"
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

    def _determine_proxy_type_for_capability(self, capability: str, injector) -> str:
        """
        Determine which proxy type to use based on parameter types that depend on this capability.

        Logic (TWO-PASS for deterministic results):
        1. First pass: Scan ALL functions to check if ANY uses McpAgent
        2. If ANY McpAgent found → use FullMCPProxy for entire capability
        3. Otherwise → use MCPClientProxy (for McpMeshAgent or default)

        This eliminates race conditions caused by function processing order.

        Args:
            capability: The capability name to check
            injector: The dependency injector instance

        Returns:
            "FullMCPProxy" or "MCPClientProxy"
        """
        try:
            # Get functions that depend on this capability
            if capability not in injector._dependency_mapping:
                self.logger.debug(
                    f"🔍 No functions depend on capability '{capability}', using MCPClientProxy"
                )
                return "MCPClientProxy"

            affected_function_ids = injector._dependency_mapping[capability]

            # PASS 1: Scan ALL functions to detect ANY McpAgent usage
            mcpagent_functions = []
            mcpmeshagent_functions = []

            for func_id in affected_function_ids:
                if func_id in injector._function_registry:
                    wrapper_func = injector._function_registry[func_id]

                    # Get stored parameter types from wrapper
                    if hasattr(wrapper_func, "_mesh_parameter_types") and hasattr(
                        wrapper_func, "_mesh_dependencies"
                    ):
                        parameter_types = wrapper_func._mesh_parameter_types
                        dependencies = wrapper_func._mesh_dependencies
                        mesh_positions = wrapper_func._mesh_positions

                        # Find which parameter position corresponds to this capability
                        for dep_index, dep_name in enumerate(dependencies):
                            if dep_name == capability and dep_index < len(
                                mesh_positions
                            ):
                                param_position = mesh_positions[dep_index]

                                # Check the parameter type at this position
                                if param_position in parameter_types:
                                    param_type = parameter_types[param_position]
                                    if param_type == "McpAgent":
                                        mcpagent_functions.append(func_id)
                                    elif param_type == "McpMeshAgent":
                                        mcpmeshagent_functions.append(func_id)

            # PASS 2: Make deterministic decision based on complete analysis
            if mcpagent_functions:
                self.logger.debug(
                    f"🔍 Found McpAgent in functions {mcpagent_functions} for capability '{capability}' → using FullMCPProxy"
                )
                if mcpmeshagent_functions:
                    self.logger.info(
                        f"ℹ️ Capability '{capability}' used by both McpAgent {mcpagent_functions} and McpMeshAgent {mcpmeshagent_functions} → upgrading ALL to FullMCPProxy"
                    )
                return "FullMCPProxy"
            else:
                # Only McpMeshAgent or untyped parameters
                self.logger.debug(
                    f"🔍 Only McpMeshAgent/untyped functions {mcpmeshagent_functions} for capability '{capability}' → using MCPClientProxy"
                )
                return "MCPClientProxy"

        except Exception as e:
            self.logger.warning(
                f"⚠️ Failed to determine proxy type for capability '{capability}': {e}"
            )
            return "MCPClientProxy"  # Safe default

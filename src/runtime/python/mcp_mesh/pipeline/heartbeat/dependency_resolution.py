"""
Dependency resolution step for MCP Mesh pipeline.

Handles processing dependency resolution from registry response and
updating the dependency injection system.
"""

import json
import logging
from typing import Any

from ...pipeline import PipelineResult, PipelineStatus
from ..startup.base_step import PipelineStep

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
        """Process dependency resolution."""
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

            # Use existing parse_tool_dependencies method from registry wrapper
            dependencies_resolved = registry_wrapper.parse_tool_dependencies(
                heartbeat_response
            )

            if not dependencies_resolved:
                result.status = PipelineStatus.SUCCESS
                result.message = "No dependencies to resolve - completed successfully"
                self.logger.info("ℹ️ No dependencies to resolve - this is normal")
                return result

            # Process each resolved dependency using existing method
            processed_deps = {}
            for function_name, dependency_list in dependencies_resolved.items():
                if isinstance(dependency_list, list):
                    for dep_resolution in dependency_list:
                        if (
                            isinstance(dep_resolution, dict)
                            and "capability" in dep_resolution
                        ):
                            capability = dep_resolution["capability"]
                            processed_deps[capability] = self._process_dependency(
                                capability, dep_resolution
                            )
                            self.logger.debug(
                                f"Processed dependency '{capability}' for function '{function_name}': "
                                f"{dep_resolution.get('endpoint', 'no-endpoint')}"
                            )

            # Store processed dependencies
            result.add_context("processed_dependencies", processed_deps)
            result.add_context("dependency_count", len(processed_deps))

            # Register dependencies with the global injector
            await self._register_dependencies_with_injector(processed_deps)

            result.message = f"Processed {len(processed_deps)} dependencies"
            self.logger.info(
                f"🔗 Dependency resolution completed: {len(processed_deps)} dependencies"
            )

            # Log dependency details
            for dep_name, dep_data in processed_deps.items():
                status = dep_data.get("status", "unknown")
                self.logger.debug(f"  - {dep_name}: {status}")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Dependency resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Dependency resolution failed: {e}")

        return result

    def _process_dependency(
        self, dep_name: str, dep_info: dict[str, Any]
    ) -> dict[str, Any]:
        """Process a single dependency."""
        # Simplified processing - just collect info for now
        # TODO: SIMPLIFICATION - Real proxy creation would happen here

        return {
            "name": dep_name,
            "status": dep_info.get("status", "unknown"),
            "agent_id": dep_info.get("agent_id"),
            "endpoint": dep_info.get("endpoint"),
            "function_name": dep_info.get("function_name"),
            "processed_at": "simplified_mode",  # TODO: Remove after simplification
        }

    async def _register_dependencies_with_injector(
        self, processed_deps: dict[str, Any]
    ) -> None:
        """Register processed dependencies with the global dependency injector."""
        try:
            # Import here to avoid circular imports
            from ...engine.dependency_injector import get_global_injector
            from ...engine.mcp_client_proxy import MCPClientProxy
            from ...engine.self_dependency_proxy import SelfDependencyProxy

            injector = get_global_injector()

            # Get current agent ID for self-dependency detection
            import os

            current_agent_id = os.getenv("MCP_MESH_AGENT_ID")
            if not current_agent_id:
                self.logger.warning(
                    "⚠️ MCP_MESH_AGENT_ID not set, self-dependency detection may fail"
                )

            for capability, dep_data in processed_deps.items():
                if dep_data.get("status") == "available":
                    endpoint = dep_data.get("endpoint")
                    function_name = dep_data.get("function_name")
                    target_agent_id = dep_data.get("agent_id")

                    if not function_name:
                        self.logger.warning(
                            f"⚠️ Cannot register dependency '{capability}': missing function_name"
                        )
                        continue

                    # Determine if this is a self-dependency by comparing agent IDs
                    is_self_dependency = (
                        current_agent_id
                        and target_agent_id
                        and current_agent_id == target_agent_id
                    )

                    if is_self_dependency:
                        # Create self-dependency proxy with cached function reference
                        original_func = injector.find_original_function(function_name)
                        if original_func:
                            proxy = SelfDependencyProxy(original_func, function_name)
                            self.logger.warning(
                                f"⚠️ SELF-DEPENDENCY: '{capability}' calls function within same agent. "
                                f"Using direct function call instead of HTTP to avoid deadlock. "
                                f"Consider refactoring to eliminate self-dependencies if possible."
                            )
                            self.logger.info(
                                f"🔄 Created SelfDependencyProxy for '{capability}' (agent: {target_agent_id})"
                            )
                        else:
                            self.logger.error(
                                f"❌ Cannot create SelfDependencyProxy for '{capability}': "
                                f"original function '{function_name}' not found"
                            )
                            continue
                    else:
                        # Create cross-service MCP client proxy
                        if not endpoint:
                            self.logger.warning(
                                f"⚠️ Cannot register cross-service dependency '{capability}': missing endpoint"
                            )
                            continue

                        proxy = MCPClientProxy(endpoint, function_name)
                        self.logger.info(
                            f"🔌 Created MCPClientProxy for '{capability}' -> {endpoint}/{function_name}"
                        )

                    # Register with injector (same interface for both proxy types)
                    await injector.register_dependency(capability, proxy)

                    # Log the final registration
                    proxy_type = "SelfDependency" if is_self_dependency else "MCP"
                    self.logger.info(f"✅ Registered {proxy_type} proxy '{capability}'")
                else:
                    self.logger.warning(
                        f"⚠️ Skipping dependency '{capability}': status = {dep_data.get('status')}"
                    )

        except Exception as e:
            self.logger.error(f"❌ Failed to register dependencies with injector: {e}")
            # Don't raise - this is not critical for pipeline to continue

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
            from ...engine.mcp_client_proxy import MCPClientProxy

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

                    if status == "available" and endpoint and dep_function_name:
                        # Import here to avoid circular imports
                        # Get current agent ID for self-dependency detection
                        import os

                        from ...engine.mcp_client_proxy import MCPClientProxy
                        from ...engine.self_dependency_proxy import SelfDependencyProxy

                        current_agent_id = os.getenv("MCP_MESH_AGENT_ID")
                        target_agent_id = dep_info.get("agent_id")

                        # Determine if this is a self-dependency
                        is_self_dependency = (
                            current_agent_id
                            and target_agent_id
                            and current_agent_id == target_agent_id
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
                                new_proxy = MCPClientProxy(endpoint, dep_function_name)
                        else:
                            # Create cross-service MCP client proxy
                            new_proxy = MCPClientProxy(endpoint, dep_function_name)
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

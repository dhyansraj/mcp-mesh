"""
LLM tools resolution step for MCP Mesh pipeline.

Handles processing llm_tools from registry response and updating
the LLM agent injection system.
"""

import json
import logging
from typing import Any

from ...engine.dependency_injector import get_global_injector
from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)

# Global state for LLM tools hash tracking across heartbeat cycles
_last_llm_tools_hash = None


class LLMToolsResolutionStep(PipelineStep):
    """
    Processes LLM tools from registry response.

    Takes the llm_tools data from the heartbeat response and updates
    the LLM agent injection system. This enables LLM agents to receive
    auto-filtered, up-to-date tool lists based on their llm_filter configuration.

    The registry applies filtering logic and returns matching tools with
    full schemas that can be used by LLM agents.
    """

    def __init__(self):
        super().__init__(
            name="llm-tools-resolution",
            required=False,  # Optional - only needed for LLM agents
            description="Process LLM tools resolution from registry",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Process LLM tools resolution with hash-based change detection."""
        self.logger.debug("Processing LLM tools resolution...")

        result = PipelineResult(message="LLM tools resolution processed")

        try:
            # Get heartbeat response
            heartbeat_response = context.get("heartbeat_response")

            if heartbeat_response is None:
                result.status = PipelineStatus.SUCCESS
                result.message = "No heartbeat response - completed successfully"
                self.logger.debug("ℹ️ No heartbeat response to process - this is normal")
                return result

            # Use hash-based change detection and processing logic
            await self.process_llm_tools_from_heartbeat(heartbeat_response)

            # Extract LLM tools count for context
            llm_tools = heartbeat_response.get("llm_tools", {})
            function_count = len(llm_tools)
            tool_count = sum(
                len(tools) if isinstance(tools, list) else 0
                for tools in llm_tools.values()
            )

            # Store processed LLM tools info for context
            result.add_context("llm_function_count", function_count)
            result.add_context("llm_tool_count", tool_count)
            result.add_context("llm_tools", llm_tools)

            result.message = "LLM tools resolution completed (efficient hash-based)"

            if function_count > 0:
                self.logger.info(
                    f"🤖 LLM tools resolved: {function_count} functions, {tool_count} tools"
                )

            self.logger.debug(
                "🤖 LLM tools resolution step completed using hash-based change detection"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"LLM tools resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ LLM tools resolution failed: {e}")

        return result

    def _extract_llm_tools_state(
        self, heartbeat_response: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """Extract LLM tools state structure from heartbeat response.

        Preserves array structure and order from registry.

        Returns:
            {function_id: [{function_name, capability, endpoint, input_schema, ...}, ...]}
        """
        llm_tools = heartbeat_response.get("llm_tools", {})

        if not isinstance(llm_tools, dict):
            self.logger.warning(f"llm_tools is not a dict, type={type(llm_tools)}")
            return {}

        # Return as-is since registry already provides the correct structure
        # Filter out non-dict or non-list values for safety
        state = {}
        for function_id, tools in llm_tools.items():
            if isinstance(tools, list):
                state[function_id] = tools

        return state

    def _hash_llm_tools_state(self, state: dict) -> str:
        """Create hash of LLM tools state structure."""
        import hashlib

        # Convert to sorted JSON string for consistent hashing
        state_json = json.dumps(state, sort_keys=True)

        hash_value = hashlib.sha256(state_json.encode()).hexdigest()[:16]

        return hash_value

    async def process_llm_tools_from_heartbeat(
        self, heartbeat_response: dict[str, Any]
    ) -> None:
        """Process heartbeat response to update LLM agent injection.

        Uses hash-based comparison to efficiently detect when ANY LLM tools change
        and then updates ALL affected LLM agents in one operation.

        Resilience logic:
        - No response (connection error, 5xx) → Skip entirely (keep existing tools)
        - 2xx response with empty llm_tools → Clear all LLM tools
        - 2xx response with partial llm_tools → Update to match registry exactly
        """
        try:
            if not heartbeat_response:
                # No response from registry (connection error, timeout, 5xx)
                # → Skip entirely for resilience (keep existing LLM tools)
                self.logger.debug(
                    "No heartbeat response - skipping LLM tools processing for resilience"
                )
                return

            # Extract current LLM tools state
            current_state = self._extract_llm_tools_state(heartbeat_response)

            # IMPORTANT: Empty state from successful response means "no LLM tools"
            # This is different from "no response" which means "keep existing for resilience"

            # Hash the current state (including empty state)
            current_hash = self._hash_llm_tools_state(current_state)

            # Compare with previous state (use global variable)
            global _last_llm_tools_hash
            if current_hash == _last_llm_tools_hash:
                self.logger.debug(
                    f"🔄 LLM tools state unchanged (hash: {current_hash}), skipping processing"
                )
                return

            # State changed - determine what changed
            function_count = len(current_state)
            total_tools = sum(len(tools) for tools in current_state.values())

            if _last_llm_tools_hash is None:
                if function_count > 0:
                    self.logger.info(
                        f"🤖 Initial LLM tools state detected: {function_count} functions, {total_tools} tools"
                    )
                else:
                    self.logger.info(
                        "🤖 Initial LLM tools state detected: no LLM tools"
                    )
            else:
                self.logger.info(
                    f"🤖 LLM tools state changed (hash: {_last_llm_tools_hash} → {current_hash})"
                )
                if function_count > 0:
                    self.logger.info(
                        f"🤖 Updating LLM tools for {function_count} functions ({total_tools} total tools)"
                    )
                else:
                    self.logger.info(
                        "🤖 Registry reports no LLM tools - clearing all existing LLM tools"
                    )

            injector = get_global_injector()

            # Determine if this is initial processing or an update
            if _last_llm_tools_hash is None:
                # Initial processing - use process_llm_tools
                self.logger.debug(
                    "🤖 Initial LLM tools processing - calling process_llm_tools()"
                )
                injector.process_llm_tools(current_state)
            else:
                # Update - use update_llm_tools
                self.logger.debug("🤖 LLM tools update - calling update_llm_tools()")
                injector.update_llm_tools(current_state)

            # Store new hash for next comparison (use global variable)
            _last_llm_tools_hash = current_hash

            if function_count > 0:
                self.logger.info(
                    f"✅ Successfully processed LLM tools for {function_count} functions ({total_tools} tools, state hash: {current_hash})"
                )
            else:
                self.logger.info(
                    f"✅ LLM tools state synchronized (no tools, state hash: {current_hash})"
                )

        except Exception as e:
            self.logger.error(
                f"❌ Failed to process LLM tools from heartbeat: {e}", exc_info=True
            )
            # Don't raise - this should not break the heartbeat loop

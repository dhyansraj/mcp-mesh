"""
Tool executor for LLM tool integration.

Handles execution of tool calls from LLM responses.
"""

import json
import logging
from typing import Any

from .llm_errors import ToolExecutionError

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Utility for executing tool calls from LLM responses.

    Handles:
    - Parsing tool call arguments
    - Finding tools in available tools list
    - Executing tools via proxies
    - Formatting results for LLM conversation
    """

    @staticmethod
    async def execute_calls(
        tool_calls: list[Any], available_tools: dict[str, Any] | list[Any]
    ) -> list[dict[str, Any]]:
        """
        Execute tool calls and return results.

        Args:
            tool_calls: List of tool call objects from LLM response
            available_tools: Dict mapping function_name -> proxy OR list of tool metadata/proxies

        Returns:
            List of tool result messages for LLM conversation

        Raises:
            ToolExecutionError: If tool execution fails
        """
        tool_results = []

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            tool_call_id = tool_call.id

            try:
                # Parse arguments
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    raise ToolExecutionError(
                        tool_name=tool_name,
                        arguments={},
                        original_error=e,
                    )

                logger.debug(f"🔧 Executing tool '{tool_name}' with args: {arguments}")

                # Find and execute tool
                result = await ToolExecutor._find_and_execute_tool(
                    tool_name, arguments, available_tools
                )

                logger.debug(f"✅ Tool '{tool_name}' executed successfully")

                # Format result for LLM
                tool_results.append(
                    ToolExecutor._format_tool_result(tool_call_id, result)
                )

            except ToolExecutionError:
                raise
            except Exception as e:
                logger.error(f"❌ Tool execution failed: {e}")
                raise ToolExecutionError(
                    tool_name=tool_name,
                    arguments=arguments if "arguments" in locals() else {},
                    original_error=e if isinstance(e, Exception) else Exception(str(e)),
                )

        return tool_results

    @staticmethod
    async def _find_and_execute_tool(
        tool_name: str, arguments: dict[str, Any], available_tools: Any
    ) -> Any:
        """
        Find tool in available tools and execute it.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments
            available_tools: Dict mapping function_name -> proxy OR list of tool metadata/proxies

        Returns:
            Tool execution result

        Raises:
            ToolExecutionError: If tool not found or execution fails
        """
        # Handle dict format (function_name -> proxy mapping)
        if isinstance(available_tools, dict):
            tool_proxy = available_tools.get(tool_name)
            if not tool_proxy:
                raise ToolExecutionError(
                    tool_name=tool_name,
                    arguments=arguments,
                    original_error=ValueError(
                        f"Tool '{tool_name}' not found in available tools"
                    ),
                )
            # Execute tool via proxy
            result = await tool_proxy.call_tool(tool_name, arguments)
            return result

        # Handle list format (legacy support)
        tool_proxy = None
        for tool in available_tools:
            # Check if it's a dict-based metadata (from registry)
            if isinstance(tool, dict) and tool.get("function_name") == tool_name:
                tool_proxy = tool
                break
            # Check if it's a proxy object (for tests)
            elif hasattr(tool, "name") and tool.name == tool_name:
                tool_proxy = tool
                break

        if not tool_proxy:
            raise ToolExecutionError(
                tool_name=tool_name,
                arguments=arguments,
                original_error=ValueError(
                    f"Tool '{tool_name}' not found in available tools"
                ),
            )

        # Execute tool
        if hasattr(tool_proxy, "call_tool"):
            # It's a proxy object with call_tool method
            result = await tool_proxy.call_tool(**arguments)
        else:
            # It's dict metadata - TODO: Execute via UnifiedMCPProxy
            result = f"Tool '{tool_name}' executed with args: {arguments}"

        return result

    @staticmethod
    def _format_tool_result(tool_call_id: str, result: Any) -> dict[str, Any]:
        """
        Format tool result for LLM conversation.

        Args:
            tool_call_id: ID of the tool call
            result: Tool execution result

        Returns:
            Formatted tool result message
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(
                result if isinstance(result, dict) else {"result": result}
            ),
        }

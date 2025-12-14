"""
Helper decorators for common mesh patterns.

This module provides convenience decorators that build on top of the core
mesh decorators to simplify common patterns like zero-code LLM providers.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def llm_provider(
    model: str,
    capability: str = "llm",
    tags: Optional[list[str]] = None,
    version: str = "1.0.0",
    **litellm_kwargs: Any,
):
    """
    Zero-code LLM provider decorator.

    Creates a mesh-registered LLM provider that automatically:
    - Registers as MCP tool (@app.tool) for direct MCP calls
    - Registers in mesh network (@mesh.tool) for dependency injection
    - Wraps LiteLLM with standard MeshLlmRequest interface
    - Returns raw string response (caller handles parsing)

    The decorated function becomes a placeholder - the decorator generates
    a process_chat(request: MeshLlmRequest) -> str function that handles
    all LLM provider logic.

    Args:
        model: LiteLLM model name (e.g., "anthropic/claude-sonnet-4-5")
        capability: Capability name for mesh registration (default: "llm")
        tags: Tags for mesh registration (e.g., ["claude", "fast", "+budget"])
        version: Version string for mesh registration (default: "1.0.0")
        **litellm_kwargs: Additional kwargs to pass to litellm.completion()

    Usage:
        from fastmcp import FastMCP
        import mesh

        app = FastMCP("LLM Provider")

        @mesh.llm_provider(
            model="anthropic/claude-sonnet-4-5",
            capability="llm",
            tags=["claude", "test"],
            version="1.0.0",
        )
        def claude_provider():
            '''Zero-code Claude provider.'''
            pass  # Implementation is in the decorator

        @mesh.agent(name="my-provider", auto_run=True)
        class MyProviderAgent:
            pass

    The generated process_chat function signature:
        def process_chat(request: MeshLlmRequest) -> str:
            '''
            Auto-generated LLM handler.

            Args:
                request: MeshLlmRequest with messages, tools, model_params

            Returns:
                Raw LLM response content as string
            '''

    Testing:
        # Direct MCP call
        curl -X POST http://localhost:9019/mcp \\
          -H "Content-Type: application/json" \\
          -d '{
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
              "name": "process_chat",
              "arguments": {
                "request": {
                  "messages": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Say hello."}
                  ]
                }
              }
            }
          }'

    Raises:
        RuntimeError: If FastMCP 'app' not found in module
        ImportError: If litellm not installed
    """

    def decorator(func):
        # Import here to avoid circular imports
        import sys

        from mesh import tool
        from mesh.types import MeshLlmRequest

        # Find FastMCP app in current module
        current_module = sys.modules.get(func.__module__)
        if not current_module or not hasattr(current_module, "app"):
            raise RuntimeError(
                f"@mesh.llm_provider requires FastMCP 'app' in module {func.__module__}. "
                f"Example: app = FastMCP('LLM Provider')"
            )

        app = current_module.app

        # Extract vendor from model name using LiteLLM
        vendor = "unknown"
        try:
            import litellm

            _, vendor, _, _ = litellm.get_llm_provider(model=model)
            logger.info(
                f"✅ Extracted vendor '{vendor}' from model '{model}' "
                f"using LiteLLM detection"
            )
        except (ImportError, AttributeError, ValueError, KeyError) as e:
            # Fallback: try to extract from model prefix
            # ImportError: litellm not installed
            # AttributeError: get_llm_provider doesn't exist
            # ValueError: invalid model format
            # KeyError: model not in provider mapping
            if "/" in model:
                vendor = model.split("/")[0]
                logger.warning(
                    f"⚠️  Could not extract vendor using LiteLLM ({e}), "
                    f"falling back to prefix extraction: '{vendor}'"
                )
            else:
                logger.warning(
                    f"⚠️  Could not extract vendor from model '{model}', "
                    f"using 'unknown'"
                )

        # Generate the LLM handler function
        def process_chat(request: MeshLlmRequest) -> dict[str, Any]:
            """
            Auto-generated LLM handler.

            Args:
                request: MeshLlmRequest with messages, tools, model_params

            Returns:
                Full message dict with content, role, and tool_calls (if present)
            """
            import litellm

            # Build litellm.completion arguments
            completion_args: dict[str, Any] = {
                "model": model,
                "messages": request.messages,
                **litellm_kwargs,
            }

            # Add optional request parameters
            if request.tools:
                completion_args["tools"] = request.tools

            if request.model_params:
                completion_args.update(request.model_params)

            # Call LiteLLM
            try:
                response = litellm.completion(**completion_args)
                message = response.choices[0].message

                # Build message dict with all necessary fields for agentic loop
                # Handle content - it can be a string or list of content blocks
                content = message.content
                if isinstance(content, list):
                    # Extract text from content blocks (robust handling)
                    text_parts = []
                    for block in content:
                        if block is None:
                            continue  # Skip None blocks
                        elif isinstance(block, dict):
                            # Extract text field, ensure it's a string
                            text_value = block.get("text", "")
                            text_parts.append(
                                str(text_value) if text_value is not None else ""
                            )
                        else:
                            # Convert any other type to string
                            try:
                                text_parts.append(str(block))
                            except Exception:
                                # If str() fails, skip this block
                                logger.warning(
                                    f"Unable to convert content block to string: {type(block)}"
                                )
                                continue
                    content = "".join(text_parts)

                message_dict: dict[str, Any] = {
                    "role": message.role,
                    "content": content if content else "",
                }

                # Include tool_calls if present (critical for agentic loop support!)
                if hasattr(message, "tool_calls") and message.tool_calls:
                    message_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ]

                logger.info(
                    f"LLM provider {func.__name__} processed request "
                    f"(model={model}, messages={len(request.messages)}, "
                    f"tool_calls={len(message_dict.get('tool_calls', []))})"
                )

                return message_dict

            except Exception as e:
                logger.error(f"LLM provider {func.__name__} failed: {e}")
                raise

        # Preserve original function's docstring metadata
        if func.__doc__:
            process_chat.__doc__ = func.__doc__ + "\n\n" + (process_chat.__doc__ or "")

        # FIX for issue #227: Preserve original function name to avoid conflicts
        # when multiple @mesh.llm_provider decorators are used in the same agent.
        # FastMCP uses __name__ as the tool name, so without this fix all providers
        # would be registered as "process_chat" and overwrite each other.
        process_chat.__name__ = func.__name__
        process_chat.__qualname__ = func.__qualname__

        # CRITICAL: Apply @mesh.tool() FIRST (before FastMCP caches the function)
        # This ensures mesh DI wrapper is in place when FastMCP caches the function
        # Decorators are applied bottom-up, so mesh wrapper must be innermost
        process_chat = tool(
            capability=capability,
            tags=tags,
            version=version,
            vendor=vendor,  # Pass vendor to registry for provider handler selection
        )(process_chat)

        # Then apply @app.tool() for MCP registration (caches the wrapped version)
        process_chat = app.tool()(process_chat)

        logger.info(
            f"✅ Created LLM provider '{func.__name__}' "
            f"(model={model}, capability={capability}, tags={tags}, vendor={vendor})"
        )

        # Return the generated function (replaces the placeholder)
        return process_chat

    return decorator

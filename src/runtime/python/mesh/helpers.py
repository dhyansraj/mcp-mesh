"""
Helper decorators for common mesh patterns.

This module provides convenience decorators that build on top of the core
mesh decorators to simplify common patterns like zero-code LLM providers.
"""

import asyncio
import json
import logging
import re
from typing import Any

from _mcp_mesh.shared.logging_config import format_log_value

logger = logging.getLogger(__name__)


def _hint_response_parses(content: str, schema: dict[str, Any]) -> bool:
    """Validate that ``content`` is JSON-parseable and conforms to ``schema``.

    Used after Claude HINT mode to decide whether to fall back to native
    response_format. Tolerant of fenced code blocks (Claude HINT can wrap
    JSON in ``\u0060\u0060\u0060json...\u0060\u0060\u0060``) — strip them before parsing.

    If ``jsonschema`` is not installed, only JSON parseability is checked.
    """
    if not content:
        return False
    try:
        cleaned = content.strip()
        # Strip surrounding markdown code fences if present.
        # Handle both ```json\n...\n``` and ```\n...\n``` patterns.
        cleaned = re.sub(
            r"^```(?:json)?\s*\n?", "", cleaned, count=1
        )
        cleaned = re.sub(r"\n?```\s*$", "", cleaned, count=1)
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return False

    try:
        import jsonschema  # type: ignore

        try:
            jsonschema.validate(instance=parsed, schema=schema)
            return True
        except jsonschema.ValidationError:
            return False
    except ImportError:
        # jsonschema not available — JSON parseability is the best we can do.
        return True


# Internal mesh control flags set by provider handlers (e.g., ClaudeHandler
# HINT mode) and consumed by the loop / legacy paths in this module. They MUST
# be stripped from completion_args before any litellm.completion call —
# otherwise providers like Anthropic reject the request with HTTP 400
# ("Extra inputs are not permitted").
_MESH_HINT_KEYS = (
    "_mesh_hint_mode",
    "_mesh_hint_schema",
    "_mesh_hint_fallback_timeout",
    "_mesh_hint_output_type_name",
)


def _pop_mesh_hint_flags(
    completion_args: dict[str, Any],
    defaults: tuple[bool, dict | None, int, str] = (False, None, 30, "Response"),
) -> tuple[bool, dict | None, int, str]:
    """Strip ``_mesh_*`` HINT-mode flags from ``completion_args`` in place.

    Returns the captured ``(hint_mode, hint_schema, hint_fallback_timeout,
    hint_output_type_name)`` so callers can use them to drive the post-call
    fallback. Defaults preserve existing values across loop iterations.
    """
    hint_mode_default, hint_schema_default, hint_timeout_default, hint_name_default = defaults
    hint_mode = bool(completion_args.pop("_mesh_hint_mode", hint_mode_default))
    hint_schema = completion_args.pop("_mesh_hint_schema", hint_schema_default)
    hint_fallback_timeout = completion_args.pop(
        "_mesh_hint_fallback_timeout", hint_timeout_default
    )
    hint_output_type_name = completion_args.pop(
        "_mesh_hint_output_type_name", hint_name_default
    )
    return hint_mode, hint_schema, hint_fallback_timeout, hint_output_type_name


async def _maybe_run_hint_fallback(
    *,
    final_content: str,
    message: Any,
    response: Any,
    base_completion_args: dict[str, Any],
    hint_mode: bool,
    hint_schema: dict[str, Any] | None,
    hint_fallback_timeout: int,
    hint_output_type_name: str,
    fallback_logger: logging.Logger | None = None,
) -> tuple[str, Any, Any]:
    """If HINT mode is active and ``final_content`` fails to parse against the
    schema, retry once with native ``response_format`` and a bounded
    ``request_timeout``.

    Returns ``(possibly-replaced final_content, message, response)``.

    Raises whatever the fallback ``litellm.completion`` raises if it fails —
    the caller is responsible for surfacing or wrapping. The original
    (HINT-mode) response is NOT retained on fallback failure: a fallback that
    errors means we couldn't recover, so re-raising is the cleanest signal.

    IMPORTANT: ``base_completion_args`` MUST already be stripped of the
    ``_mesh_*`` HINT keys AND of the ``tools`` key. The helper does NOT strip
    ``tools`` itself — that's the caller's responsibility. Stripping ``tools``
    matters because the fallback only fires AFTER the model returned final
    content with no tool_calls, and re-introducing the ``response_format +
    tools`` combo would re-create the silent-hang vector from issue #820.
    """
    if not (hint_mode and hint_schema and final_content):
        return final_content, message, response

    if _hint_response_parses(final_content, hint_schema):
        return final_content, message, response

    if fallback_logger:
        fallback_logger.warning(
            "Claude HINT mode response failed to parse against output schema; "
            "retrying with native response_format (bounded request_timeout=%ss)",
            hint_fallback_timeout,
        )

    fallback_args = {
        **base_completion_args,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": hint_output_type_name,
                "schema": hint_schema,
                "strict": True,
            },
        },
        "request_timeout": hint_fallback_timeout,
    }
    # Lazy import keeps this module importable in environments without
    # litellm (e.g., during static analysis); both call sites already
    # import litellm before invoking this helper.
    import litellm

    fallback_response = await asyncio.to_thread(
        litellm.completion, **fallback_args
    )
    fb_message = fallback_response.choices[0].message
    fb_content = _extract_text_from_message_content(fb_message.content)

    if fallback_logger:
        fallback_logger.info("Claude HINT fallback to response_format succeeded")

    return (fb_content if fb_content else "", fb_message, fallback_response)


def _extract_text_from_message_content(content: Any) -> str:
    """Normalize a LiteLLM message ``content`` field to a plain string.

    LiteLLM may return ``content`` as a string (most providers) or as a list
    of content blocks (Anthropic with thinking, mixed text+image, etc.). This
    helper handles both shapes and concatenates text blocks.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if block is None:
                continue
            if isinstance(block, dict):
                text_value = block.get("text", "")
                text_parts.append(
                    str(text_value) if text_value is not None else ""
                )
            else:
                try:
                    text_parts.append(str(block))
                except Exception:
                    continue
        return "".join(text_parts)
    return str(content)


async def _provider_agentic_loop(
    effective_model: str,
    messages: list,
    tools: list,
    tool_endpoints: dict[str, str],
    model_params: dict,
    litellm_kwargs: dict,
    max_iterations: int = 10,
    loop_logger: logging.Logger | None = None,
    vendor: str | None = None,
) -> dict[str, Any]:
    """Execute tools provider-side and return final response.

    Runs a full agentic loop on the provider: calls the LLM, executes any
    tool calls via MCP proxies, feeds results back, and repeats until the
    LLM produces a final text response (no tool calls).

    Args:
        effective_model: LiteLLM model identifier to use.
        messages: Conversation messages (will be copied internally).
        tools: OpenAI-format tool schemas (already cleaned of _mesh_endpoint).
        tool_endpoints: Mapping of tool_name -> MCP endpoint URL.
        model_params: Extra model parameters for litellm.completion().
        litellm_kwargs: Base kwargs captured by the decorator.
        max_iterations: Safety limit on loop iterations.
        loop_logger: Logger instance for debug/info output.
        vendor: Vendor name for media resolution (e.g., "anthropic", "openai").

    Returns:
        Message dict with role, content, and optionally _mesh_usage.
    """
    import litellm

    from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy
    from _mcp_mesh.media.resolver import _has_resource_link, resolve_resource_links

    # Vendors that do NOT support images in tool/function result messages.
    # OpenAI strictly rejects images in role:tool messages.
    # For these vendors, images are accumulated and sent as one user message
    # after ALL tool results for the iteration.
    _tool_image_unsupported = {"openai", "gemini", "google"}

    iteration = 0
    current_messages = list(messages)

    # Pop parallel_tool_calls before it reaches completion_args
    # (Claude handler strips it, but OpenAI would pass it to API)
    parallel = model_params.pop("parallel_tool_calls", False)
    if parallel and loop_logger:
        loop_logger.info("🔀 Provider parallel tool calls enabled — tools will execute concurrently via asyncio.gather()")

    async def _execute_single_tool(tc) -> tuple[dict, list[dict]]:
        """Execute a single tool call and return (tool_message, image_parts)."""
        tool_name = tc.function.name
        endpoint = tool_endpoints.get(tool_name)

        if not endpoint:
            if loop_logger:
                loop_logger.warning(
                    f"No endpoint for tool {tool_name}, returning error"
                )
            return (
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(
                        {"error": f"Tool {tool_name} not available"}
                    ),
                },
                [],
            )

        try:
            args = (
                json.loads(tc.function.arguments)
                if tc.function.arguments
                else {}
            )
            proxy = UnifiedMCPProxy(
                endpoint=endpoint, function_name=tool_name
            )
            result = await proxy.call_tool(tool_name, args)

            # Resolve resource_link items to multimodal content.
            # Always use OpenAI-compatible format (image_url with
            # data URIs) — LiteLLM converts to provider-native.
            if vendor and _has_resource_link(result):
                try:
                    # Always use OpenAI format — LiteLLM converts to
                    # provider-native format internally.
                    resolved_parts = await resolve_resource_links(
                        result, "openai"
                    )
                except Exception as resolve_err:
                    if loop_logger:
                        loop_logger.error(f"Media resolution failed: {resolve_err}")
                    resolved_parts = []

                image_types = ("image", "image_url")
                has_image = any(
                    p.get("type") in image_types
                    for p in resolved_parts
                )

                if has_image:
                    if vendor in _tool_image_unsupported:
                        # OpenAI/Gemini: images NOT allowed in tool messages.
                        # Put text-only parts in the tool message, accumulate
                        # images for a single user message after all tool results.
                        text_parts = [
                            p for p in resolved_parts
                            if p.get("type") not in image_types
                        ]
                        image_parts = [
                            p for p in resolved_parts
                            if p.get("type") in image_types
                        ]

                        # Ensure tool message has at least some content
                        if not text_parts:
                            text_parts = [{"type": "text", "text": "[Image from tool result]"}]

                        # OpenAI requires tool message content to be a string
                        if len(text_parts) == 1:
                            tool_content = text_parts[0].get("text", "")
                        else:
                            tool_content = json.dumps(text_parts)

                        if loop_logger:
                            loop_logger.debug(
                                f"Tool {tool_name} result: {len(text_parts)} text parts in tool msg, "
                                f"{len(image_parts)} images accumulated (vendor={vendor})"
                            )
                        return (
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": tool_content,
                            },
                            image_parts,
                        )
                    else:
                        # Claude/Anthropic via LiteLLM: inline images in tool message.
                        # LiteLLM converts image_url data URIs to the provider's native
                        # format (Claude base64 blocks, etc.).
                        if loop_logger:
                            loop_logger.debug(
                                f"Tool {tool_name} result: resolved {len(resolved_parts)} "
                                f"multimodal parts inline (vendor={vendor})"
                            )
                        return (
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": resolved_parts,
                            },
                            [],
                        )
                else:
                    # Non-image resource_links resolved to text — use resolved text
                    text_content = "\n".join(
                        p.get("text", "") for p in resolved_parts if p.get("type") == "text"
                    )
                    if text_content:
                        tool_result = text_content
                    else:
                        tool_result = json.dumps(result)
                    if loop_logger:
                        loop_logger.debug(
                            f"Tool {tool_name} result: resolved non-image resource_link to text "
                            f"({len(text_content)} chars, vendor={vendor})"
                        )
                    # Fall through to normal message append
            elif isinstance(result, (dict, list)):
                tool_result = json.dumps(result)
            elif result is None:
                tool_result = ""
            else:
                tool_result = str(result)

            if loop_logger:
                loop_logger.debug(
                    f"Tool {tool_name} result: {tool_result[:200]}"
                )
        except Exception as e:
            if loop_logger:
                loop_logger.error(f"Tool {tool_name} execution failed: {e}")
            tool_result = json.dumps({"error": str(e)})

        return (
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            },
            [],
        )

    # HINT-mode state (set by ClaudeHandler.apply_structured_output).
    # Captured outside the loop so the fallback after the loop has access.
    hint_mode = False
    hint_schema: dict[str, Any] | None = None
    hint_fallback_timeout = 30
    hint_output_type_name = "Response"

    while iteration < max_iterations:
        iteration += 1

        completion_args: dict[str, Any] = {
            "model": effective_model,
            "messages": current_messages,
            "tools": tools,
            **litellm_kwargs,
        }
        if model_params:
            completion_args.update(model_params)

        # Strip internal mesh control flags before they reach LiteLLM.
        # These are set by handlers (e.g., ClaudeHandler HINT mode) to
        # signal post-processing to the loop. Must run every iteration
        # because model_params is unconditionally re-applied above.
        # NOTE: The legacy single-call path below (in ``llm_provider``) does
        # the SAME strip — keep both in sync.
        (
            hint_mode,
            hint_schema,
            hint_fallback_timeout,
            hint_output_type_name,
        ) = _pop_mesh_hint_flags(
            completion_args,
            defaults=(
                hint_mode,
                hint_schema,
                hint_fallback_timeout,
                hint_output_type_name,
            ),
        )

        response = await asyncio.to_thread(litellm.completion, **completion_args)
        message = response.choices[0].message

        if hasattr(message, "tool_calls") and message.tool_calls:
            if loop_logger:
                loop_logger.debug(
                    f"Provider executing {len(message.tool_calls)} tool calls "
                    f"(iteration {iteration}/{max_iterations})"
                )

            # Add assistant message with tool_calls to conversation
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
            current_messages.append(assistant_msg)

            accumulated_images: list[dict] = []

            if parallel and len(message.tool_calls) > 1:
                # Parallel execution via asyncio.gather
                if loop_logger:
                    loop_logger.info(
                        f"⚡ Provider executing {len(message.tool_calls)} tool calls in parallel"
                    )
                results = await asyncio.gather(
                    *[_execute_single_tool(tc) for tc in message.tool_calls]
                )
                for tool_msg, images in results:
                    current_messages.append(tool_msg)
                    accumulated_images.extend(images)
            else:
                # Sequential execution (original behavior)
                for tc in message.tool_calls:
                    tool_msg, images = await _execute_single_tool(tc)
                    current_messages.append(tool_msg)
                    accumulated_images.extend(images)

            # After ALL tool results: inject accumulated images as one user message.
            # Sequence: assistant(tool_calls) -> tool -> tool -> ... -> user(images)
            # This is valid because it comes after all tool results and before the
            # next LLM call.
            if accumulated_images:
                current_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Here are the images from the tool results above:"},
                        *accumulated_images,
                    ],
                })
                if loop_logger:
                    loop_logger.info(
                        f"Injected user message with {len(accumulated_images)} accumulated images "
                        f"(vendor={vendor})"
                    )
        else:
            # No tool calls - final response
            final_content = _extract_text_from_message_content(message.content)

            # HINT-mode validation + bounded-timeout fallback (issue #820).
            # If a handler (currently only ClaudeHandler) signaled HINT mode,
            # validate the final response against the schema. If it fails to
            # parse, retry once with native response_format and a hard timeout.
            # This recovers from HINT compliance failures without re-introducing
            # the silent 600s+ hang of the unbounded response_format path.
            #
            # Build base args for the fallback — strip ``tools`` since the
            # fallback only fires AFTER the model gave a final answer with no
            # tool_calls. Keeping ``tools`` would re-introduce the
            # ``response_format + tools`` combo that caused the original
            # silent hang (issue #820). Bounded timeout is still there as
            # defense-in-depth, but stripping tools removes the deadlock
            # vector entirely.
            fallback_base_args = {
                k: v for k, v in completion_args.items() if k != "tools"
            }
            try:
                final_content, message, response = await _maybe_run_hint_fallback(
                    final_content=final_content,
                    message=message,
                    response=response,
                    base_completion_args=fallback_base_args,
                    hint_mode=hint_mode,
                    hint_schema=hint_schema,
                    hint_fallback_timeout=hint_fallback_timeout,
                    hint_output_type_name=hint_output_type_name,
                    fallback_logger=loop_logger,
                )
            except Exception as e:
                if loop_logger:
                    loop_logger.error(
                        "Claude HINT fallback to response_format failed: %s",
                        e,
                    )
                raise

            message_dict: dict[str, Any] = {
                "role": message.role,
                "content": final_content,
            }

            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                message_dict["_mesh_usage"] = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "model": effective_model,
                }

            if loop_logger:
                loop_logger.info(
                    f"Provider-managed loop completed in {iteration} iterations"
                )

            return message_dict

    # Safety: max iterations reached
    if loop_logger:
        loop_logger.warning(
            f"Provider-managed loop hit max iterations ({max_iterations})"
        )
    return {
        "role": "assistant",
        "content": "Maximum tool call iterations reached",
    }


def _extract_vendor_from_model(model: str) -> str | None:
    """
    Extract vendor name from LiteLLM model string.

    LiteLLM uses vendor/model format (e.g., "anthropic/claude-sonnet-4-5").
    This extracts the vendor for provider handler selection.

    Args:
        model: LiteLLM model string

    Returns:
        Vendor name (e.g., "anthropic", "openai") or None if not extractable

    Examples:
        "anthropic/claude-sonnet-4-5" -> "anthropic"
        "openai/gpt-4o" -> "openai"
        "gpt-4" -> None (no vendor prefix)
    """
    if not model:
        return None

    if "/" in model:
        vendor = model.split("/")[0].lower().strip()
        return vendor

    return None


def llm_provider(
    model: str,
    capability: str = "llm",
    tags: list[str] | None = None,
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
        async def process_chat(request: MeshLlmRequest) -> dict[str, Any]:
            """
            Auto-generated LLM handler.

            Args:
                request: MeshLlmRequest with messages, tools, model_params

            Returns:
                Full message dict with content, role, and tool_calls (if present)
            """
            import litellm

            # Determine effective model (check for consumer override - issue #308)
            effective_model = model  # Default to provider's model
            model_params_copy = (
                dict(request.model_params) if request.model_params else {}
            )

            if "model" in model_params_copy:
                override_model = model_params_copy.pop(
                    "model"
                )  # Remove to avoid duplication

                if override_model:
                    # Validate vendor compatibility
                    override_vendor = _extract_vendor_from_model(override_model)

                    if override_vendor and override_vendor != vendor:
                        # Vendor mismatch - log warning and fall back to provider's model
                        logger.warning(
                            f"⚠️ Model override '{override_model}' ignored - vendor mismatch "
                            f"(override vendor: '{override_vendor}', provider vendor: '{vendor}'). "
                            f"Using provider's default model: '{model}'"
                        )
                    else:
                        # Vendor matches or can't be determined - use override
                        effective_model = override_model
                        logger.info(
                            f"🔄 Using model override '{effective_model}' "
                            f"(requested by consumer)"
                        )

            # Get vendor handler once - used for both structured output and system prompt formatting
            from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

            handler = ProviderHandlerRegistry.get_handler(vendor)

            # Issue #459: Handle output_schema for vendor-specific structured output
            # Use provider handler pattern for vendor-specific behavior
            output_schema = model_params_copy.pop("output_schema", None)
            output_type_name = model_params_copy.pop("output_type_name", None)

            if output_schema:
                # Include messages so handler can modify system prompt (e.g., HINT mode injection)
                model_params_copy["messages"] = request.messages
                handler.apply_structured_output(
                    output_schema, output_type_name, model_params_copy
                )
                # Remove messages to avoid duplication in completion_args
                model_params_copy.pop("messages", None)
                logger.debug(
                    f"🎯 Applied {vendor} structured output via handler: "
                    f"{output_type_name}"
                )

            # Check if tools have mesh endpoints for provider-side execution
            tool_endpoints: dict[str, str] = {}
            clean_tools: list[dict[str, Any]] | None = None
            if request.tools:
                clean_tools = []
                for req_tool in request.tools:
                    func_def = req_tool.get("function", {})
                    endpoint = func_def.pop("_mesh_endpoint", None)
                    if endpoint:
                        tool_endpoints[func_def.get("name", "")] = endpoint
                    clean_tools.append(req_tool)

            # Use vendor handler to format system prompt when tools are present
            effective_tools = clean_tools if clean_tools is not None else request.tools
            messages = request.messages
            if effective_tools:

                # Find and format system message
                formatted_messages = []
                for msg in messages:
                    if msg.get("role") == "system":
                        # Format system prompt with vendor-specific instructions
                        base_prompt = msg.get("content", "")
                        formatted_content = handler.format_system_prompt(
                            base_prompt=base_prompt,
                            tool_schemas=effective_tools,
                            output_type=str,  # Provider returns raw string
                        )
                        formatted_messages.append(
                            {"role": "system", "content": formatted_content}
                        )
                    else:
                        formatted_messages.append(msg)
                messages = formatted_messages

            if tool_endpoints:
                # Provider-managed agentic loop: execute tools internally
                logger.info(
                    f"Provider-managed loop: {len(tool_endpoints)} tools with endpoints"
                )
                message_dict = await _provider_agentic_loop(
                    effective_model=effective_model,
                    messages=messages,
                    tools=clean_tools or [],
                    tool_endpoints=tool_endpoints,
                    model_params=model_params_copy,
                    litellm_kwargs=litellm_kwargs,
                    max_iterations=10,
                    loop_logger=logger,
                    vendor=vendor,
                )

                logger.info(
                    f"LLM provider {func.__name__} processed request via provider loop "
                    f"(model={effective_model}, messages={len(request.messages)})"
                )

                return message_dict

            # Legacy path: single LLM call, return tool_calls to consumer
            completion_args: dict[str, Any] = {
                "model": effective_model,
                "messages": messages,
                **litellm_kwargs,
            }

            if effective_tools:
                completion_args["tools"] = effective_tools

            if model_params_copy:
                completion_args.update(model_params_copy)

            # Strip internal mesh control flags before they reach LiteLLM.
            # These are set by handlers (e.g., ClaudeHandler HINT mode) and
            # would otherwise cause provider APIs to reject the request with
            # HTTP 400 ("Extra inputs are not permitted"). The HINT fallback
            # below uses the captured values.
            # NOTE: The provider-managed loop above does the SAME strip —
            # see ``_provider_agentic_loop`` for the multi-iteration path.
            (
                hint_mode,
                hint_schema,
                hint_fallback_timeout,
                hint_output_type_name,
            ) = _pop_mesh_hint_flags(completion_args)

            try:
                logger.debug(
                    f"📤 LLM provider request: {format_log_value(completion_args)}"
                )

                response = await asyncio.to_thread(
                    litellm.completion, **completion_args
                )

                logger.debug(f"📥 LLM provider response: {format_log_value(response)}")

                message = response.choices[0].message

                # Handle content - it can be a string or list of content blocks
                final_content = _extract_text_from_message_content(message.content)

                # HINT-mode validation + bounded-timeout fallback (issue #820).
                # Mirrors the same logic in ``_provider_agentic_loop``. Without
                # this, a HINT compliance failure here would surface as a
                # ResponseParseError to the consumer.
                # NOTE: only run when there are no tool_calls — if the model
                # returned tools, structured output is not yet expected.
                no_tool_calls = not (
                    hasattr(message, "tool_calls") and message.tool_calls
                )
                if hint_mode and no_tool_calls:
                    # Build base args for the fallback — strip ``tools`` since
                    # the fallback only fires AFTER the model gave a final
                    # answer with no tool_calls. Keeping ``tools`` would
                    # re-introduce the ``response_format + tools`` combo that
                    # caused the original silent hang (issue #820). Bounded
                    # timeout is still there as defense-in-depth, but stripping
                    # tools removes the deadlock vector entirely.
                    fallback_base_args = {
                        k: v for k, v in completion_args.items() if k != "tools"
                    }
                    try:
                        final_content, message, response = await _maybe_run_hint_fallback(
                            final_content=final_content,
                            message=message,
                            response=response,
                            base_completion_args=fallback_base_args,
                            hint_mode=hint_mode,
                            hint_schema=hint_schema,
                            hint_fallback_timeout=hint_fallback_timeout,
                            hint_output_type_name=hint_output_type_name,
                            fallback_logger=logger,
                        )
                    except Exception as fallback_err:
                        logger.error(
                            "Claude HINT fallback to response_format failed: %s",
                            fallback_err,
                        )
                        raise

                message_dict: dict[str, Any] = {
                    "role": message.role,
                    "content": final_content if final_content else "",
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

                # Issue #311: Include usage metadata for cost tracking
                if hasattr(response, "usage") and response.usage:
                    usage = response.usage
                    message_dict["_mesh_usage"] = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0)
                        or 0,
                        "model": effective_model,
                    }

                logger.info(
                    f"LLM provider {func.__name__} processed request "
                    f"(model={effective_model}, messages={len(request.messages)}, "
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

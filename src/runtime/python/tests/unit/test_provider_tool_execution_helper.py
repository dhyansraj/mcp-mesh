"""
Unit tests for ``_execute_tool_calls_for_iteration`` (mesh.helpers).

Background:
    Phase 1 of the mesh-delegate streaming work for issue #849 extracted the
    per-iteration tool dispatch logic out of ``_provider_agentic_loop`` into a
    standalone async helper. The helper is also intended for reuse by the
    Phase 2 streaming provider loop. These tests pin down the helper's
    contract directly (independent of the surrounding agentic loop) so that
    future refactors do not silently change behavior.

    The helper imports ``UnifiedMCPProxy`` and the resolver functions inside
    its body, so patches must target the original module paths.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mesh.helpers import (
    _TOOL_IMAGE_UNSUPPORTED_VENDORS,
    _execute_tool_calls_for_iteration,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_function_mock(name: str, arguments: str):
    func = MagicMock()
    func.name = name
    func.arguments = arguments
    return func


def _make_tool_call_mock(id: str, name: str, arguments: str = "{}"):
    """Build a tool_call mock matching the litellm message shape."""
    tool_call = MagicMock()
    tool_call.id = id
    tool_call.type = "function"
    tool_call.function = _make_function_mock(name, arguments)
    return tool_call


def _make_message_mock(tool_calls: list):
    """Build a litellm-style message mock with .tool_calls."""
    message = MagicMock()
    message.tool_calls = tool_calls
    return message


# ---------------------------------------------------------------------------
# Sequential / parallel dispatch
# ---------------------------------------------------------------------------


class TestSequentialAndParallelDispatch:
    """Verify the parallel vs sequential branch and the returned tuple shape."""

    @pytest.mark.asyncio
    async def test_single_sequential_tool_call(self):
        """One tool call, parallel=False -> 1 tool message, 0 images."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "echo", '{"x": 1}')]
        )
        tool_endpoints = {"echo": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(return_value="hello")

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ):
            tool_messages, images = await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="anthropic",
                loop_logger=None,
            )

        assert len(tool_messages) == 1
        assert images == []
        assert tool_messages[0]["role"] == "tool"
        assert tool_messages[0]["tool_call_id"] == "call_1"
        assert tool_messages[0]["content"] == "hello"
        proxy_instance.call_tool.assert_awaited_once_with("echo", {"x": 1})

    @pytest.mark.asyncio
    async def test_two_parallel_tool_calls(self):
        """Two tool calls, parallel=True -> 2 tool messages (in order), 0 images."""
        message = _make_message_mock(
            [
                _make_tool_call_mock("call_1", "tool_a", "{}"),
                _make_tool_call_mock("call_2", "tool_b", "{}"),
            ]
        )
        tool_endpoints = {
            "tool_a": "http://localhost:9001",
            "tool_b": "http://localhost:9002",
        }

        # Each UnifiedMCPProxy() invocation returns a different mock instance.
        # Map by function_name so call_tool returns distinct results.
        def proxy_factory(endpoint: str, function_name: str):
            inst = MagicMock()
            inst.call_tool = AsyncMock(return_value=f"result-{function_name}")
            return inst

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            side_effect=proxy_factory,
        ):
            tool_messages, images = await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=True,
                vendor="anthropic",
                loop_logger=None,
            )

        assert len(tool_messages) == 2
        assert images == []
        # Order must match message.tool_calls order — even with asyncio.gather,
        # the helper preserves declaration order in the returned list.
        assert tool_messages[0]["tool_call_id"] == "call_1"
        assert tool_messages[0]["content"] == "result-tool_a"
        assert tool_messages[1]["tool_call_id"] == "call_2"
        assert tool_messages[1]["content"] == "result-tool_b"

    @pytest.mark.asyncio
    async def test_parallel_with_single_call_uses_sequential_path(self):
        """parallel=True with len(tool_calls)==1 falls through to the sequential
        branch — there is no benefit to ``asyncio.gather`` for a single call,
        and the original loop made the same micro-optimization."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "echo", "{}")]
        )
        tool_endpoints = {"echo": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(return_value="ok")

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ):
            tool_messages, images = await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=True,
                vendor="anthropic",
                loop_logger=None,
            )

        assert len(tool_messages) == 1
        assert tool_messages[0]["content"] == "ok"
        assert images == []


# ---------------------------------------------------------------------------
# Vendor-specific image handling
# ---------------------------------------------------------------------------


class TestVendorImageHandling:
    """Verify the image accumulation contract for vendors that do/don't allow
    images in role:tool messages."""

    def _patch_resolver(self, has_image: bool, parts: list):
        """Patch ``_has_resource_link`` to return True and
        ``resolve_resource_links`` to return the supplied parts."""
        return (
            patch(
                "_mcp_mesh.media.resolver._has_resource_link",
                return_value=True,
            ),
            patch(
                "_mcp_mesh.media.resolver.resolve_resource_links",
                new=AsyncMock(return_value=parts),
            ),
        )

    @pytest.mark.asyncio
    async def test_image_with_openai_vendor_accumulates_image(self):
        """vendor=openai: image part is stripped from the tool message and
        accumulated for a follow-up user message; tool message gets a stub
        ``[Image from tool result]`` text."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(return_value={"resource_link": True})

        image_part = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AAA", "detail": "high"},
        }

        link_patch, resolve_patch = self._patch_resolver(
            has_image=True, parts=[image_part]
        )
        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), link_patch, resolve_patch:
            tool_messages, images = await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="openai",
                loop_logger=None,
            )

        assert len(tool_messages) == 1
        assert tool_messages[0]["role"] == "tool"
        assert tool_messages[0]["tool_call_id"] == "call_1"
        # No text parts in resolved output -> stub text in tool message.
        assert tool_messages[0]["content"] == "[Image from tool result]"
        assert images == [image_part]

    @pytest.mark.asyncio
    async def test_image_with_anthropic_vendor_inlines_image(self):
        """vendor=anthropic: resolved multimodal parts are inlined as the tool
        message content; nothing accumulated for a follow-up user message."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(return_value={"resource_link": True})

        resolved_parts = [
            {"type": "text", "text": "Screenshot of homepage"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,AAA",
                    "detail": "high",
                },
            },
        ]

        link_patch, resolve_patch = self._patch_resolver(
            has_image=True, parts=resolved_parts
        )
        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), link_patch, resolve_patch:
            tool_messages, images = await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="anthropic",
                loop_logger=None,
            )

        assert len(tool_messages) == 1
        assert tool_messages[0]["role"] == "tool"
        assert tool_messages[0]["tool_call_id"] == "call_1"
        # Multimodal parts inlined verbatim (LiteLLM converts to native format).
        assert tool_messages[0]["content"] == resolved_parts
        assert images == []


# ---------------------------------------------------------------------------
# Endpoint-missing / error handling
# ---------------------------------------------------------------------------


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_missing_endpoint_returns_error_tool_message(self):
        """Tool with no endpoint -> error tool message with JSON error
        content; UnifiedMCPProxy is NOT constructed, no images."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "ghost_tool", "{}")]
        )
        tool_endpoints: dict[str, str] = {}  # no endpoint registered

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy"
        ) as proxy_cls:
            tool_messages, images = await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="anthropic",
                loop_logger=None,
            )

        assert images == []
        assert len(tool_messages) == 1
        assert tool_messages[0]["role"] == "tool"
        assert tool_messages[0]["tool_call_id"] == "call_1"
        # Content is a JSON-encoded error envelope.
        decoded = json.loads(tool_messages[0]["content"])
        assert decoded == {"error": "Tool ghost_tool not available"}
        # The proxy class is never instantiated for missing endpoints.
        proxy_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_tool_image_unsupported_vendors_set(self):
        """The vendor set drives image-handling policy; if it changes,
        provider-side image behavior changes silently. Pin it explicitly."""
        assert _TOOL_IMAGE_UNSUPPORTED_VENDORS == {"openai", "gemini", "google"}

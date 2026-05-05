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
    _warn_native_dispatch_unknown_vendor_once,
)
import mesh.helpers as _mesh_helpers


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
# Issue #860 — vendor-native upstream emission on the native dispatch path
# (and OpenAI-shape fallback on the LiteLLM path)
# ---------------------------------------------------------------------------


class TestNativeDispatchResolverVendor:
    """Verify the ``has_native_dispatch`` flag drives the vendor argument
    passed to ``resolve_resource_links``. This is the upstream half of the
    #860 architectural cleanup: native dispatch path receives vendor-native
    content blocks straight from the resolver; LiteLLM fallback path keeps
    the historical OpenAI-shape contract so LiteLLM's own vendor adapters
    handle the conversion."""

    def _patch_resolver(self, parts: list):
        """Patch the resolver so we can capture the vendor argument."""
        resolve_mock = AsyncMock(return_value=parts)
        return (
            patch(
                "_mcp_mesh.media.resolver._has_resource_link",
                return_value=True,
            ),
            patch(
                "_mcp_mesh.media.resolver.resolve_resource_links",
                new=resolve_mock,
            ),
            resolve_mock,
        )

    @pytest.mark.asyncio
    async def test_litellm_path_uses_openai_shape_for_anthropic_vendor(self):
        """LiteLLM fallback path (``has_native_dispatch=False``): even though
        vendor is "anthropic", the resolver is asked for OpenAI shape so the
        existing LiteLLM adapter chain keeps working unchanged."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(
            return_value={"resource_link": True}
        )

        link_patch, resolve_patch, resolve_mock = self._patch_resolver(
            parts=[{"type": "text", "text": "ok"}]
        )

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), link_patch, resolve_patch:
            await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="anthropic",
                loop_logger=None,
                has_native_dispatch=False,
            )

        assert resolve_mock.await_count == 1
        # Second positional arg is the vendor passed to the resolver.
        called_vendor = resolve_mock.await_args.args[1]
        assert called_vendor == "openai", (
            "LiteLLM fallback path must keep emitting OpenAI-shape blocks; "
            f"got vendor={called_vendor!r}"
        )

    @pytest.mark.asyncio
    async def test_native_dispatch_uses_vendor_native_shape_for_anthropic(self):
        """Native dispatch path (``has_native_dispatch=True``): vendor flows
        through to the resolver so the resolver emits Claude-native image
        blocks directly. The native Anthropic adapter's content-block
        translator becomes a no-op for these blocks."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(
            return_value={"resource_link": True}
        )

        link_patch, resolve_patch, resolve_mock = self._patch_resolver(
            parts=[{"type": "text", "text": "ok"}]
        )

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), link_patch, resolve_patch:
            await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="anthropic",
                loop_logger=None,
                has_native_dispatch=True,
            )

        assert resolve_mock.await_count == 1
        called_vendor = resolve_mock.await_args.args[1]
        assert called_vendor == "anthropic", (
            "Native dispatch path must emit vendor-native blocks; "
            f"got vendor={called_vendor!r}"
        )

    @pytest.mark.asyncio
    async def test_native_dispatch_uses_vendor_native_shape_for_gemini(self):
        """Native dispatch + vendor=gemini: resolver is called with "gemini".
        The resolver's ``_format_for_gemini`` is currently aliased to
        ``_format_for_openai``, so the wire shape is identical to the
        LiteLLM path — but the call CONTRACT is "ask for gemini" so future
        gemini-native shape changes flow through automatically."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(
            return_value={"resource_link": True}
        )

        link_patch, resolve_patch, resolve_mock = self._patch_resolver(
            parts=[{"type": "text", "text": "ok"}]
        )

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), link_patch, resolve_patch:
            await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="gemini",
                loop_logger=None,
                has_native_dispatch=True,
            )

        assert resolve_mock.await_count == 1
        called_vendor = resolve_mock.await_args.args[1]
        assert called_vendor == "gemini"

    @pytest.mark.asyncio
    async def test_default_has_native_dispatch_preserves_legacy_behavior(self):
        """Callers that don't yet plumb ``has_native_dispatch`` (third-party
        or mid-rebase) MUST get the pre-#860 behavior: resolver called with
        OpenAI shape, LiteLLM downstream handles conversion."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(
            return_value={"resource_link": True}
        )

        link_patch, resolve_patch, resolve_mock = self._patch_resolver(
            parts=[{"type": "text", "text": "ok"}]
        )

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), link_patch, resolve_patch:
            # Note: no has_native_dispatch kwarg -> default False.
            await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="anthropic",
                loop_logger=None,
            )

        assert resolve_mock.await_args.args[1] == "openai"

    @pytest.mark.asyncio
    async def test_native_dispatch_with_none_vendor_skips_resolver(self):
        """When vendor is None on the native dispatch path, the upstream
        ``vendor and _has_resource_link(...)`` short-circuit prevents resolver
        invocation entirely. (Unknown-but-non-None vendor fallback is covered
        separately in TestUnknownNativeVendorWarn.)"""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(
            return_value={"resource_link": True}
        )

        link_patch, resolve_patch, resolve_mock = self._patch_resolver(
            parts=[{"type": "text", "text": "ok"}]
        )

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), link_patch, resolve_patch:
            await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor=None,
                loop_logger=None,
                has_native_dispatch=True,
            )

        # When vendor is None, the resolver guard inside the helper means the
        # resolver shouldn't even be invoked (it's gated on
        # ``vendor and _has_resource_link(result)``). Pin that fact.
        assert resolve_mock.await_count == 0


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_tool_image_unsupported_vendors_set(self):
        """The vendor set drives image-handling policy; if it changes,
        provider-side image behavior changes silently. Pin it explicitly."""
        assert _TOOL_IMAGE_UNSUPPORTED_VENDORS == {"openai", "gemini", "google"}


# ---------------------------------------------------------------------------
# Issue #860 cleanup — WARN when native dispatch claims an unknown vendor
# ---------------------------------------------------------------------------


class TestUnknownNativeVendorWarn:
    """The native dispatch path validates ``vendor`` against
    ``_VENDOR_FORMATTERS``; an unknown vendor falls back to OpenAI shape but
    emits a one-time WARN so the operator notices the misconfiguration
    instead of silently shipping wrong content blocks."""

    @pytest.fixture(autouse=True)
    def _reset_dedupe(self):
        """Per-vendor dedupe set persists for the process; reset between
        tests so each one observes the WARN-once behavior cleanly."""
        _mesh_helpers._logged_unknown_native_vendors.clear()
        yield
        _mesh_helpers._logged_unknown_native_vendors.clear()

    def test_warn_emits_once_per_vendor(self, caplog):
        with caplog.at_level("WARNING", logger=_mesh_helpers.logger.name):
            _warn_native_dispatch_unknown_vendor_once("brand_new_vendor")
            _warn_native_dispatch_unknown_vendor_once("brand_new_vendor")
            _warn_native_dispatch_unknown_vendor_once("brand_new_vendor")

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "brand_new_vendor" in r.getMessage()
        ]
        assert len(warn_msgs) == 1, (
            f"expected exactly one WARN per unique vendor; got "
            f"{len(warn_msgs)}: {warn_msgs}"
        )

    def test_warn_emits_once_per_unique_vendor(self, caplog):
        """Distinct unknown vendors each get their own one-shot WARN."""
        with caplog.at_level("WARNING", logger=_mesh_helpers.logger.name):
            _warn_native_dispatch_unknown_vendor_once("vendor_a")
            _warn_native_dispatch_unknown_vendor_once("vendor_b")
            _warn_native_dispatch_unknown_vendor_once("vendor_a")
            _warn_native_dispatch_unknown_vendor_once("vendor_c")

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "_VENDOR_FORMATTERS" in r.getMessage()
        ]
        # Three distinct vendors → three WARNs total.
        assert len(warn_msgs) == 3
        assert sum("vendor_a" in m for m in warn_msgs) == 1
        assert sum("vendor_b" in m for m in warn_msgs) == 1
        assert sum("vendor_c" in m for m in warn_msgs) == 1

    @pytest.mark.asyncio
    async def test_native_dispatch_with_unknown_vendor_warns_and_falls_back(
        self, caplog
    ):
        """End-to-end: ``_execute_tool_calls_for_iteration`` with
        has_native_dispatch=True and a vendor not in _VENDOR_FORMATTERS must
        (a) call the resolver with vendor="openai" (safe fallback) and
        (b) emit the WARN."""
        message = _make_message_mock(
            [_make_tool_call_mock("call_1", "screenshot", "{}")]
        )
        tool_endpoints = {"screenshot": "http://localhost:9000"}

        proxy_instance = MagicMock()
        proxy_instance.call_tool = AsyncMock(
            return_value={"resource_link": True}
        )

        resolve_mock = AsyncMock(return_value=[{"type": "text", "text": "ok"}])

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.UnifiedMCPProxy",
            return_value=proxy_instance,
        ), patch(
            "_mcp_mesh.media.resolver._has_resource_link", return_value=True
        ), patch(
            "_mcp_mesh.media.resolver.resolve_resource_links", new=resolve_mock
        ), caplog.at_level("WARNING", logger=_mesh_helpers.logger.name):
            await _execute_tool_calls_for_iteration(
                message=message,
                tool_endpoints=tool_endpoints,
                parallel=False,
                vendor="cohere",  # not in _VENDOR_FORMATTERS today
                loop_logger=None,
                has_native_dispatch=True,
            )

        # Resolver was called with the safe fallback vendor.
        assert resolve_mock.await_count == 1
        assert resolve_mock.await_args.args[1] == "openai"

        # WARN fired once for the unknown vendor.
        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "cohere" in r.getMessage()
        ]
        assert len(warn_msgs) == 1, (
            f"expected one WARN about unknown native vendor 'cohere'; "
            f"got: {warn_msgs}"
        )

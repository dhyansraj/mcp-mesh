"""Unit tests for issue #849 Stage A: provider tool's @mesh.llm_provider /
@mesh.tool kwargs must reach the consumer-side provider proxy via the
registry's resolved LLM provider event.

Mirrors the producer-kwargs propagation tests for regular tool dependencies
(``test_dep_event_kwargs_propagation.py``). The fix flows:

  Producer @mesh.llm_provider → registry stores capability.kwargs
  Registry resolves provider → ResolvedLLMProvider.kwargs (Go)
  Wire → Rust ResolvedLlmProvider.kwargs → LlmProviderInfo.kwargs (JSON string)
  Python event handler parses kwargs → injector dict["kwargs"]
  MeshLlmAgentInjector._create_provider_proxy spreads dict["kwargs"]
  into proxy.kwargs_config so streaming etc. is configured.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# rust_heartbeat._handle_llm_provider_update — parses provider_info.kwargs
# and forwards it through ``injector.process_llm_providers``.
# ---------------------------------------------------------------------------


class TestLlmProviderUpdateForwardsKwargs:
    @pytest.mark.asyncio
    async def test_provider_kwargs_reach_provider_proxy(self):
        """provider_info.kwargs JSON must be parsed and reach
        ``injector.process_llm_providers`` keyed under ``kwargs``."""
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        provider_info = SimpleNamespace(
            function_id="chat_abc123",
            function_name="process_chat_stream",
            endpoint="http://provider:9170",
            agent_id="claude-provider",
            model="anthropic/claude-sonnet-4-5",
            vendor="anthropic",
            kwargs=json.dumps({"stream_type": "text", "vendor": "anthropic"}),
        )

        injector = MagicMock()
        injector.register_dependency = AsyncMock()
        injector.process_llm_providers = MagicMock()

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_global_injector",
            return_value=injector,
        ), patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
            MagicMock(),
        ):
            await rust_heartbeat._handle_llm_provider_update(
                provider_info=provider_info,
                context={},
            )

        injector.process_llm_providers.assert_called_once()
        call_arg = injector.process_llm_providers.call_args.args[0]
        assert "chat_abc123" in call_arg
        provider_data = call_arg["chat_abc123"]
        assert provider_data["kwargs"] == {
            "stream_type": "text",
            "vendor": "anthropic",
        }

    @pytest.mark.asyncio
    async def test_provider_kwargs_absent_yields_empty_dict(self):
        """When the provider tool ships no kwargs, the dict's ``kwargs``
        slot must be present and empty — not missing."""
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        provider_info = SimpleNamespace(
            function_id="chat_abc123",
            function_name="process_chat",
            endpoint="http://provider:9170",
            agent_id="claude-provider",
            model="anthropic/claude-sonnet-4-5",
            vendor="anthropic",
            kwargs=None,
        )

        injector = MagicMock()
        injector.register_dependency = AsyncMock()
        injector.process_llm_providers = MagicMock()

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_global_injector",
            return_value=injector,
        ), patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
            MagicMock(),
        ):
            await rust_heartbeat._handle_llm_provider_update(
                provider_info=provider_info,
                context={},
            )

        call_arg = injector.process_llm_providers.call_args.args[0]
        assert call_arg["chat_abc123"]["kwargs"] == {}

    @pytest.mark.asyncio
    async def test_provider_kwargs_invalid_json_falls_back(self, caplog):
        """Malformed JSON must be logged and fall back to empty dict —
        the proxy is still constructed."""
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        provider_info = SimpleNamespace(
            function_id="chat_abc123",
            function_name="process_chat",
            endpoint="http://provider:9170",
            agent_id="claude-provider",
            model="anthropic/claude-sonnet-4-5",
            vendor="anthropic",
            kwargs="not-json{",
        )

        injector = MagicMock()
        injector.register_dependency = AsyncMock()
        injector.process_llm_providers = MagicMock()

        with caplog.at_level("WARNING"), patch(
            "_mcp_mesh.engine.dependency_injector.get_global_injector",
            return_value=injector,
        ), patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
            MagicMock(),
        ):
            await rust_heartbeat._handle_llm_provider_update(
                provider_info=provider_info,
                context={},
            )

        call_arg = injector.process_llm_providers.call_args.args[0]
        assert call_arg["chat_abc123"]["kwargs"] == {}
        assert any(
            "Could not parse provider kwargs" in r.message for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_provider_info_without_kwargs_attr_is_safe(self):
        """Forward-compat with older Rust core that doesn't ship the kwargs
        attribute on provider_info — getattr fallback to None must work."""
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        # Build provider_info WITHOUT the kwargs attribute at all.
        provider_info = SimpleNamespace(
            function_id="chat_abc123",
            function_name="process_chat",
            endpoint="http://provider:9170",
            agent_id="claude-provider",
            model="anthropic/claude-sonnet-4-5",
            vendor="anthropic",
        )

        injector = MagicMock()
        injector.register_dependency = AsyncMock()
        injector.process_llm_providers = MagicMock()

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_global_injector",
            return_value=injector,
        ), patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
            MagicMock(),
        ):
            await rust_heartbeat._handle_llm_provider_update(
                provider_info=provider_info,
                context={},
            )

        call_arg = injector.process_llm_providers.call_args.args[0]
        assert call_arg["chat_abc123"]["kwargs"] == {}


# ---------------------------------------------------------------------------
# MeshLlmAgentInjector._create_provider_proxy — spreads provider_data["kwargs"]
# onto the proxy's kwargs_config.
# ---------------------------------------------------------------------------


class TestCreateProviderProxySpreadsKwargs:
    def test_provider_kwargs_lifted_onto_proxy_kwargs_config(self):
        """``provider_data["kwargs"]`` must be spread onto the proxy's
        ``kwargs_config`` alongside the existing ``capability`` / ``agent_id``
        keys. This is what Stage A unblocks for streaming."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()

        captured: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured["endpoint"] = endpoint
                captured["function_name"] = function_name
                captured["kwargs_config"] = kwargs_config

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent_injector.UnifiedMCPProxy", FakeProxy
        ):
            injector._create_provider_proxy(
                {
                    "name": "process_chat_stream",
                    "endpoint": "http://provider:9170",
                    "capability": "llm",
                    "agent_id": "claude-provider",
                    "kwargs": {"stream_type": "text", "vendor": "anthropic"},
                }
            )

        assert captured["endpoint"] == "http://provider:9170"
        assert captured["function_name"] == "process_chat_stream"
        assert captured["kwargs_config"] == {
            "capability": "llm",
            "agent_id": "claude-provider",
            "stream_type": "text",
            "vendor": "anthropic",
        }

    def test_provider_kwargs_absent_yields_today_behavior(self):
        """No ``kwargs`` key in provider_data → kwargs_config matches the
        pre-fix two-key dict. Verifies we didn't regress the buffered path."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()

        captured: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured["function_name"] = function_name
                captured["kwargs_config"] = kwargs_config

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent_injector.UnifiedMCPProxy", FakeProxy
        ):
            injector._create_provider_proxy(
                {
                    "name": "process_chat",
                    "endpoint": "http://provider:9170",
                    "capability": "llm",
                    "agent_id": "claude-provider",
                    # No "kwargs" key — older registry / non-streaming provider.
                }
            )

        # CRITICAL: function_name unchanged → buffered tool routing preserved.
        assert captured["function_name"] == "process_chat"
        assert captured["kwargs_config"] == {
            "capability": "llm",
            "agent_id": "claude-provider",
        }
        assert "stream_type" not in captured["kwargs_config"]

    def test_provider_kwargs_none_handled_gracefully(self):
        """``provider_data["kwargs"]`` explicitly None must not crash —
        the spread must coerce to an empty dict."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()

        captured: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured["kwargs_config"] = kwargs_config

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent_injector.UnifiedMCPProxy", FakeProxy
        ):
            injector._create_provider_proxy(
                {
                    "name": "process_chat",
                    "endpoint": "http://provider:9170",
                    "capability": "llm",
                    "agent_id": "claude-provider",
                    "kwargs": None,
                }
            )

        assert captured["kwargs_config"] == {
            "capability": "llm",
            "agent_id": "claude-provider",
        }

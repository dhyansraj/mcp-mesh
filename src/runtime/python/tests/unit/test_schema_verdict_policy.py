"""
Unit tests for the issue #547 Phase 4 schema verdict policy helpers in
``_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat``.
"""

import os
from unittest.mock import patch

import pytest

from _mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat import (
    _cluster_strict_enabled,
    _should_refuse_startup,
)


class TestShouldRefuseStartup:
    def test_ok_never_refuses(self):
        assert _should_refuse_startup("OK", cluster_strict=False, tool_strict=True) is False
        assert _should_refuse_startup("OK", cluster_strict=True, tool_strict=True) is False
        assert _should_refuse_startup("OK", cluster_strict=True, tool_strict=False) is False

    def test_block_with_default_tool_strict_refuses(self):
        # Default behavior: BLOCK refuses startup.
        assert (
            _should_refuse_startup("BLOCK", cluster_strict=False, tool_strict=True)
            is True
        )

    def test_block_with_per_tool_override_does_not_refuse(self):
        # Per-tool escape hatch demotes BLOCK to WARN for that tool.
        assert (
            _should_refuse_startup("BLOCK", cluster_strict=False, tool_strict=False)
            is False
        )

    def test_warn_with_defaults_does_not_refuse(self):
        # Default behavior: WARN logs but doesn't refuse.
        assert (
            _should_refuse_startup("WARN", cluster_strict=False, tool_strict=True)
            is False
        )

    def test_warn_with_cluster_strict_refuses(self):
        # Cluster strict promotes WARN to BLOCK.
        assert (
            _should_refuse_startup("WARN", cluster_strict=True, tool_strict=True)
            is True
        )

    def test_per_tool_override_wins_over_cluster_strict(self):
        # Per-tool override is the producer's explicit opt-out and wins even
        # when ops have flipped the cluster-wide knob.
        assert (
            _should_refuse_startup("BLOCK", cluster_strict=True, tool_strict=False)
            is False
        )
        assert (
            _should_refuse_startup("WARN", cluster_strict=True, tool_strict=False)
            is False
        )


class TestClusterStrictEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "YES"])
    def test_truthy_values(self, value):
        with patch.dict(os.environ, {"MCP_MESH_SCHEMA_STRICT": value}):
            assert _cluster_strict_enabled() is True

    @pytest.mark.parametrize(
        "value", ["", "0", "false", "no", "off", "anything-else"]
    )
    def test_falsy_values(self, value):
        with patch.dict(os.environ, {"MCP_MESH_SCHEMA_STRICT": value}):
            assert _cluster_strict_enabled() is False

    def test_unset_is_false(self):
        env = {k: v for k, v in os.environ.items() if k != "MCP_MESH_SCHEMA_STRICT"}
        with patch.dict(os.environ, env, clear=True):
            assert _cluster_strict_enabled() is False


class TestToolDecoratorAcceptsFlag:
    def test_decorator_accepts_output_schema_strict(self):
        import mesh

        @mesh.tool(capability="test_cap", output_schema_strict=False)
        def my_tool():
            return "ok"

        meta = getattr(my_tool, "_mesh_tool_metadata", None)
        assert meta is not None
        assert meta.get("output_schema_strict") is False

    def test_decorator_default_is_true(self):
        import mesh

        @mesh.tool(capability="test_cap_default")
        def my_tool_default():
            return "ok"

        meta = getattr(my_tool_default, "_mesh_tool_metadata", None)
        assert meta is not None
        assert meta.get("output_schema_strict") is True

    def test_decorator_rejects_non_bool(self):
        import mesh

        with pytest.raises(ValueError, match="output_schema_strict must be a boolean"):
            @mesh.tool(capability="bad", output_schema_strict="yes")  # type: ignore[arg-type]
            def my_bad_tool():
                return "ok"

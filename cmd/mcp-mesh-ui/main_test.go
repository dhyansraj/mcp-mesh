package main

import (
	"os"
	"testing"
)

func TestResolveConsumerGroup(t *testing.T) {
	t.Run("unset keeps the historical default", func(t *testing.T) {
		// t.Setenv registers the restore; unset after it to test the absent case.
		t.Setenv("MCP_MESH_UI_TRACE_CONSUMER_GROUP", "")
		if err := os.Unsetenv("MCP_MESH_UI_TRACE_CONSUMER_GROUP"); err != nil {
			t.Fatalf("unsetenv: %v", err)
		}
		if got := resolveConsumerGroup(); got != "mcp-mesh-ui-dashboard" {
			t.Errorf("resolveConsumerGroup() = %q, want %q", got, "mcp-mesh-ui-dashboard")
		}
	})

	t.Run("empty is treated as unset", func(t *testing.T) {
		t.Setenv("MCP_MESH_UI_TRACE_CONSUMER_GROUP", "")
		if got := resolveConsumerGroup(); got != "mcp-mesh-ui-dashboard" {
			t.Errorf("resolveConsumerGroup() = %q, want %q", got, "mcp-mesh-ui-dashboard")
		}
	})

	t.Run("set overrides", func(t *testing.T) {
		t.Setenv("MCP_MESH_UI_TRACE_CONSUMER_GROUP", "mcp-mesh-ui-scratch")
		if got := resolveConsumerGroup(); got != "mcp-mesh-ui-scratch" {
			t.Errorf("resolveConsumerGroup() = %q, want %q", got, "mcp-mesh-ui-scratch")
		}
	})
}

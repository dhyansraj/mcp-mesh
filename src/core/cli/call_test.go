package cli

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestFormatMCPError_DuplicatesCollapsed covers issue #956 item #11:
// when the outer Error.Message and the nested Error.Data.message are
// the same string, render it once.
func TestFormatMCPError_DuplicatesCollapsed(t *testing.T) {
	dup := "job_id is required"
	err := formatMCPError(&MCPError{
		Code:    -32602,
		Message: dup,
		Data:    map[string]interface{}{"message": dup},
	})
	if err == nil {
		t.Fatal("expected non-nil error")
	}
	// The same string must not appear twice (separated by ": ", which is
	// how formatMCPError would append a non-duplicate Data).
	if strings.Contains(err.Error(), dup+": "+dup) {
		t.Errorf("error message contains the duplicate twice: %q", err.Error())
	}
	if err.Error() != dup {
		t.Errorf("expected %q, got %q", dup, err.Error())
	}
}

// TestFormatMCPError_PydanticURLStripped covers issue #956 item #10:
// Pydantic appends "For further information visit https://errors.pydantic.dev/..."
// trailers that are noise to CLI users.
func TestFormatMCPError_PydanticURLStripped(t *testing.T) {
	err := formatMCPError(&MCPError{
		Code:    -32602,
		Message: "validation error",
		Data: "1 validation error for JobStatusRequest\njob_id\n  Field required [type=missing, input_value={}, input_type=dict]\n" +
			"    For further information visit https://errors.pydantic.dev/2.5/v/missing",
	})
	if err == nil {
		t.Fatal("expected non-nil error")
	}
	got := err.Error()
	if strings.Contains(got, "pydantic.dev") {
		t.Errorf("formatMCPError did not strip pydantic.dev URL:\n%s", got)
	}
	if strings.Contains(got, "For further information visit") {
		t.Errorf("formatMCPError did not strip 'For further information visit' line:\n%s", got)
	}
	if !strings.Contains(got, "Field required") {
		t.Errorf("formatMCPError dropped the actual validation message:\n%s", got)
	}
}

// TestFormatMCPError_DataAddsInfo confirms that when Error.Data carries
// genuinely-new content (not a duplicate of Error.Message) it is appended.
func TestFormatMCPError_DataAddsInfo(t *testing.T) {
	err := formatMCPError(&MCPError{
		Code:    -32603,
		Message: "internal error",
		Data:    "agent panicked at line 42",
	})
	got := err.Error()
	if !strings.Contains(got, "internal error") {
		t.Errorf("missing top-level message: %s", got)
	}
	if !strings.Contains(got, "agent panicked at line 42") {
		t.Errorf("missing data detail: %s", got)
	}
}

// TestFormatMCPError_NilData renders just the message.
func TestFormatMCPError_NilData(t *testing.T) {
	err := formatMCPError(&MCPError{Code: -32601, Message: "method not found"})
	if err.Error() != "method not found" {
		t.Errorf("got %q, want %q", err.Error(), "method not found")
	}
}

// TestExtractMCPErrorData_PydanticValidationList exercises the list-shaped
// Pydantic validation payload.
func TestExtractMCPErrorData_PydanticValidationList(t *testing.T) {
	data := []interface{}{
		map[string]interface{}{
			"type": "missing",
			"loc":  []interface{}{"body", "job_id"},
			"msg":  "Field required",
		},
	}
	got := extractMCPErrorData(data)
	if !strings.Contains(got, "Field required") {
		t.Errorf("missing msg in extracted data: %s", got)
	}
	if !strings.Contains(got, "job_id") {
		t.Errorf("missing loc in extracted data: %s", got)
	}
}

// TestStripPydanticDevURLs handles both inline URLs and trailing "For
// further information visit" lines.
func TestStripPydanticDevURLs(t *testing.T) {
	in := "validation error\nFor further information visit https://errors.pydantic.dev/2.5/v/missing\nother line"
	out := stripPydanticDevURLs(in)
	if strings.Contains(out, "pydantic.dev") {
		t.Errorf("URL not stripped: %s", out)
	}
	if !strings.Contains(out, "validation error") {
		t.Errorf("real message dropped: %s", out)
	}
	if !strings.Contains(out, "other line") {
		t.Errorf("unrelated line dropped: %s", out)
	}

	// No-op when there's nothing to strip.
	clean := "plain error message"
	if stripPydanticDevURLs(clean) != clean {
		t.Errorf("stripPydanticDevURLs altered clean input: %q", stripPydanticDevURLs(clean))
	}
}

// TestFormatToolCollisionError covers issue #956 items #13/#14: when more
// than one healthy agent registers the same tool name, the error must list
// candidates and include a usable disambiguation hint.
func TestFormatToolCollisionError(t *testing.T) {
	rows := []toolCollisionRow{
		{AgentID: "foo-aaa", AgentName: "foo", ToolName: "do_thing"},
		{AgentID: "bar-bbb", AgentName: "bar", ToolName: "do_thing"},
	}
	err := formatToolCollisionError("call", "do_thing", rows)
	if err == nil {
		t.Fatal("expected non-nil error")
	}
	msg := err.Error()

	for _, want := range []string{
		"multiple healthy agents",
		"foo-aaa:do_thing",
		"bar-bbb:do_thing",
		"agent name: foo",
		"agent name: bar",
		"meshctl call foo-aaa:do_thing",
	} {
		if !strings.Contains(msg, want) {
			t.Errorf("collision error missing %q\nmsg:\n%s", want, msg)
		}
	}

	// `list` variant emits the list-style example.
	listErr := formatToolCollisionError("list", "do_thing", rows)
	if !strings.Contains(listErr.Error(), "meshctl list --tools=foo-aaa:do_thing") {
		t.Errorf("list variant missing list-style example:\n%s", listErr.Error())
	}
}

// TestIsFrameworkInternalTool covers the filter that hides __mesh_job_*
// tools from `meshctl list --tools` by default (issue #956 #15).
func TestIsFrameworkInternalTool(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want bool
	}{
		{"job_status framework", "__mesh_job_status", true},
		{"job_result framework", "__mesh_job_result", true},
		{"job_cancel framework", "__mesh_job_cancel", true},
		{"normal tool", "get_weather", false},
		{"dunder but not mesh_job", "__init__", false},
		{"empty", "", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := isFrameworkInternalTool(c.in); got != c.want {
				t.Errorf("isFrameworkInternalTool(%q) = %v, want %v", c.in, got, c.want)
			}
		})
	}
}

// mockRegistryWithAgents returns an httptest server that serves the given
// agents at GET /agents. Used to exercise findAgentWithTool / *Ingress.
func mockRegistryWithAgents(t *testing.T, agents []AgentWithCapabilities) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"agents": agents,
		})
	}))
}

// TestFindAgentWithTool_FrameworkInternalBypassAmbiguity covers the
// regression fix for `meshctl call __mesh_job_*` when multiple agents
// register the helper. __mesh_job_* helpers auto-register on every
// MeshJob-capable agent and share registry-backed state — picking any
// healthy match is semantically correct.
func TestFindAgentWithTool_FrameworkInternalBypassAmbiguity(t *testing.T) {
	agents := []AgentWithCapabilities{
		{
			ID:       "agent-a-aaa",
			Name:     "agent-a",
			Endpoint: "http://agent-a:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "__mesh_job_status", FunctionName: "__mesh_job_status"},
			},
		},
		{
			ID:       "agent-b-bbb",
			Name:     "agent-b",
			Endpoint: "http://agent-b:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "__mesh_job_status", FunctionName: "__mesh_job_status"},
			},
		},
	}
	srv := mockRegistryWithAgents(t, agents)
	defer srv.Close()

	endpoint, funcName, err := findAgentWithTool(http.DefaultClient, srv.URL, "", "__mesh_job_status")
	if err != nil {
		t.Fatalf("expected no error for bare __mesh_job_status with 2 healthy agents, got: %v", err)
	}
	if endpoint == "" {
		t.Errorf("expected non-empty endpoint, got empty")
	}
	if funcName != "__mesh_job_status" {
		t.Errorf("expected function name __mesh_job_status, got %q", funcName)
	}
	// Verify it picked the first match (semantically: any healthy is correct).
	if endpoint != "http://agent-a:8080" {
		t.Errorf("expected first match endpoint http://agent-a:8080, got %q", endpoint)
	}
}

// TestFindAgentWithTool_CapabilityToolStillAmbiguous is the regression
// guard: capability tools (non-framework) MUST still error on collision.
func TestFindAgentWithTool_CapabilityToolStillAmbiguous(t *testing.T) {
	agents := []AgentWithCapabilities{
		{
			ID:       "agent-a-aaa",
			Name:     "agent-a",
			Endpoint: "http://agent-a:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "commission_report_async", FunctionName: "commission_report_async"},
			},
		},
		{
			ID:       "agent-b-bbb",
			Name:     "agent-b",
			Endpoint: "http://agent-b:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "commission_report_async", FunctionName: "commission_report_async"},
			},
		},
	}
	srv := mockRegistryWithAgents(t, agents)
	defer srv.Close()

	_, _, err := findAgentWithTool(http.DefaultClient, srv.URL, "", "commission_report_async")
	if err == nil {
		t.Fatal("expected ambiguity error for bare commission_report_async with 2 healthy agents")
	}
	if !strings.Contains(err.Error(), "multiple healthy agents") {
		t.Errorf("expected 'multiple healthy agents' in error, got: %v", err)
	}
}

// TestFindAgentWithToolIngress_FrameworkInternalBypassAmbiguity is the
// ingress-path counterpart to the bypass test above.
func TestFindAgentWithToolIngress_FrameworkInternalBypassAmbiguity(t *testing.T) {
	agents := []AgentWithCapabilities{
		{
			ID:       "agent-a-aaa",
			Name:     "agent-a",
			Endpoint: "http://agent-a-mcp-mesh-agent.mcp-mesh:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "__mesh_job_status", FunctionName: "__mesh_job_status"},
			},
		},
		{
			ID:       "agent-b-bbb",
			Name:     "agent-b",
			Endpoint: "http://agent-b-mcp-mesh-agent.mcp-mesh:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "__mesh_job_status", FunctionName: "__mesh_job_status"},
			},
		},
	}
	srv := mockRegistryWithAgents(t, agents)
	defer srv.Close()

	extractedName, agentHost, funcName, err := findAgentWithToolIngress(http.DefaultClient, srv.URL, "example.com", "", "__mesh_job_status")
	if err != nil {
		t.Fatalf("expected no error for bare __mesh_job_status with 2 healthy agents, got: %v", err)
	}
	if extractedName == "" {
		t.Errorf("expected non-empty extracted name")
	}
	if agentHost == "" {
		t.Errorf("expected non-empty agent host")
	}
	if funcName != "__mesh_job_status" {
		t.Errorf("expected function name __mesh_job_status, got %q", funcName)
	}
	// First match should be agent-a.
	if extractedName != "agent-a" {
		t.Errorf("expected first match extracted name agent-a, got %q", extractedName)
	}
}

// TestFindAgentWithToolIngress_CapabilityToolStillAmbiguous regression guard.
func TestFindAgentWithToolIngress_CapabilityToolStillAmbiguous(t *testing.T) {
	agents := []AgentWithCapabilities{
		{
			ID:       "agent-a-aaa",
			Name:     "agent-a",
			Endpoint: "http://agent-a-mcp-mesh-agent.mcp-mesh:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "commission_report_async", FunctionName: "commission_report_async"},
			},
		},
		{
			ID:       "agent-b-bbb",
			Name:     "agent-b",
			Endpoint: "http://agent-b-mcp-mesh-agent.mcp-mesh:8080",
			Status:   "healthy",
			Capabilities: []ToolInfo{
				{Name: "commission_report_async", FunctionName: "commission_report_async"},
			},
		},
	}
	srv := mockRegistryWithAgents(t, agents)
	defer srv.Close()

	_, _, _, err := findAgentWithToolIngress(http.DefaultClient, srv.URL, "example.com", "", "commission_report_async")
	if err == nil {
		t.Fatal("expected ambiguity error for bare commission_report_async with 2 healthy agents")
	}
	if !strings.Contains(err.Error(), "multiple healthy agents") {
		t.Errorf("expected 'multiple healthy agents' in error, got: %v", err)
	}
}

// TestParseHeaderFlags covers --header/-H parsing (Issue #1084): malformed
// entries error, valid entries set headers, whitespace is trimmed, empty
// values are allowed, repeated keys accumulate, and empty input is a no-op.
func TestParseHeaderFlags(t *testing.T) {
	t.Run("no colon errors", func(t *testing.T) {
		_, err := parseHeaderFlags([]string{"Authorization Bearer abc"})
		if err == nil {
			t.Fatal("expected error for header with no colon")
		}
	})

	t.Run("empty key errors", func(t *testing.T) {
		_, err := parseHeaderFlags([]string{": value"})
		if err == nil {
			t.Fatal("expected error for empty key")
		}
	})

	t.Run("valid single header", func(t *testing.T) {
		h, err := parseHeaderFlags([]string{"Authorization: Bearer abc"})
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got := h.Get("Authorization"); got != "Bearer abc" {
			t.Errorf("got %q, want %q", got, "Bearer abc")
		}
	})

	t.Run("whitespace trimmed", func(t *testing.T) {
		h, err := parseHeaderFlags([]string{"  Key :  val "})
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if _, ok := h["Key"]; !ok {
			t.Errorf("expected canonical key %q in %v", "Key", h)
		}
		if got := h.Get("Key"); got != "val" {
			t.Errorf("got %q, want %q", got, "val")
		}
	})

	t.Run("empty value allowed", func(t *testing.T) {
		h, err := parseHeaderFlags([]string{"X-Flag:"})
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		vals, ok := h["X-Flag"]
		if !ok || len(vals) != 1 || vals[0] != "" {
			t.Errorf("expected one empty value for X-Flag, got %v", h)
		}
	})

	t.Run("repeated key accumulates", func(t *testing.T) {
		h, err := parseHeaderFlags([]string{"X-Multi: a", "X-Multi: b"})
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		vals := h["X-Multi"]
		if len(vals) != 2 || vals[0] != "a" || vals[1] != "b" {
			t.Errorf("expected [a b] for X-Multi, got %v", vals)
		}
	})

	t.Run("value with colon preserved", func(t *testing.T) {
		h, err := parseHeaderFlags([]string{"X-URL: http://example.com:8080"})
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got := h.Get("X-URL"); got != "http://example.com:8080" {
			t.Errorf("got %q, want %q", got, "http://example.com:8080")
		}
	})

	t.Run("empty input is nil no error", func(t *testing.T) {
		h, err := parseHeaderFlags(nil)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if h != nil {
			t.Errorf("expected nil header for empty input, got %v", h)
		}
	})
}

// mockMCPAgent returns an httptest server that captures the headers of the
// last received request and replies with a minimal valid MCP result.
func mockMCPAgent(t *testing.T, captured *http.Header) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*captured = r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(MCPResponse{
			JSONRPC: "2.0",
			ID:      1,
			Result:  json.RawMessage(`{"ok":true}`),
		})
	}))
}

// TestCallMCPTool_UserHeadersAndFrameworkPrecedence covers Issue #1084:
// user-supplied headers reach the agent, but framework-managed headers
// (Content-Type, X-Trace-ID, X-Mesh-Timeout) always win on conflict.
func TestCallMCPTool_UserHeadersAndFrameworkPrecedence(t *testing.T) {
	var got http.Header
	srv := mockMCPAgent(t, &got)
	defer srv.Close()

	traceCtx := &TraceContext{TraceID: "real-framework-trace", SpanID: "span-1"}
	userHeaders, err := parseHeaderFlags([]string{
		"Authorization: Bearer abc",
		"X-Trace-ID: user-should-lose",
		"Content-Type: text/plain",
	})
	if err != nil {
		t.Fatalf("parseHeaderFlags failed: %v", err)
	}

	_, err = callMCPTool(http.DefaultClient, srv.URL, "do_thing", map[string]interface{}{}, userHeaders, traceCtx, 30)
	if err != nil {
		t.Fatalf("callMCPTool failed: %v", err)
	}

	if got.Get("Authorization") != "Bearer abc" {
		t.Errorf("custom header not forwarded: Authorization=%q", got.Get("Authorization"))
	}
	if got.Get("X-Trace-ID") != "real-framework-trace" {
		t.Errorf("framework X-Trace-ID should win, got %q", got.Get("X-Trace-ID"))
	}
	if got.Get("Content-Type") != "application/json" {
		t.Errorf("framework Content-Type should win, got %q", got.Get("Content-Type"))
	}
	if got.Get("X-Mesh-Timeout") != "30" {
		t.Errorf("framework X-Mesh-Timeout should be set, got %q", got.Get("X-Mesh-Timeout"))
	}
}

// TestCallMCPToolWithHost_UserHeadersAndFrameworkPrecedence is the
// ingress-path counterpart for Issue #1084.
func TestCallMCPToolWithHost_UserHeadersAndFrameworkPrecedence(t *testing.T) {
	var got http.Header
	srv := mockMCPAgent(t, &got)
	defer srv.Close()

	traceCtx := &TraceContext{TraceID: "real-framework-trace", SpanID: "span-1"}
	userHeaders, err := parseHeaderFlags([]string{
		"Authorization: Bearer abc",
		"X-Trace-ID: user-should-lose",
	})
	if err != nil {
		t.Fatalf("parseHeaderFlags failed: %v", err)
	}

	_, err = callMCPToolWithHost(http.DefaultClient, srv.URL, "", "do_thing", map[string]interface{}{}, userHeaders, traceCtx, 30)
	if err != nil {
		t.Fatalf("callMCPToolWithHost failed: %v", err)
	}

	if got.Get("Authorization") != "Bearer abc" {
		t.Errorf("custom header not forwarded: Authorization=%q", got.Get("Authorization"))
	}
	if got.Get("X-Trace-ID") != "real-framework-trace" {
		t.Errorf("framework X-Trace-ID should win, got %q", got.Get("X-Trace-ID"))
	}
}

// --- extractMCPResponseJSON / SSE extraction (#1201) ---

const sseContentType = "text/event-stream; charset=utf-8"

// TestExtractMCPResponseJSON_CommentOnlyTimeoutShaped covers the #1201
// repro: the proxy's X-Mesh-Timeout cap cut the stream after only an
// sse-starlette keepalive comment arrived. The result must be a
// timeout-shaped error naming the budget and the --timeout remedy — and
// must NOT contain the raw comment text.
func TestExtractMCPResponseJSON_CommentOnlyTimeoutShaped(t *testing.T) {
	body := []byte(": ping - 2026-06-09 12:00:00.000000+00:00\r\n\r\n")
	_, _, err := extractMCPResponseJSON(body, sseContentType, 30*time.Second, 30)
	if err == nil {
		t.Fatal("expected error for comment-only SSE stream, got nil")
	}
	msg := err.Error()
	for _, want := range []string{"timed out", "X-Mesh-Timeout", "30", "--timeout"} {
		if !strings.Contains(msg, want) {
			t.Errorf("timeout error missing %q:\n%s", want, msg)
		}
	}
	if strings.Contains(msg, "ping") {
		t.Errorf("raw keepalive comment leaked into the error: %s", msg)
	}
}

// TestExtractMCPResponseJSON_QuickEmptyStreamProtocolError distinguishes a
// stream that ended well within the budget: that's the agent (or proxy)
// closing early, not a timeout — the error must not claim a timeout.
func TestExtractMCPResponseJSON_QuickEmptyStreamProtocolError(t *testing.T) {
	body := []byte("event: message\n\n")
	_, _, err := extractMCPResponseJSON(body, sseContentType, 2*time.Second, 30)
	if err == nil {
		t.Fatal("expected error for data-less SSE stream, got nil")
	}
	msg := err.Error()
	if strings.Contains(msg, "timed out") {
		t.Errorf("quick empty stream must not be reported as a timeout: %s", msg)
	}
	if !strings.Contains(msg, "without sending a response") {
		t.Errorf("protocol error missing explanation: %s", msg)
	}
}

// TestExtractMCPResponseJSON_ProxyMarkerForcesTimeout covers the registry
// proxy's terminal `: mesh-proxy-timeout` comment frame: when present, the
// error is timeout-shaped even if local elapsed time is below the budget
// (e.g. the proxy's own MCP_MESH_PROXY_TIMEOUT default fired first).
func TestExtractMCPResponseJSON_ProxyMarkerForcesTimeout(t *testing.T) {
	body := []byte(": ping - keepalive\n\n: mesh-proxy-timeout budget=30s\n\n")
	_, _, err := extractMCPResponseJSON(body, sseContentType, 5*time.Second, 60)
	if err == nil {
		t.Fatal("expected error for marker-terminated SSE stream, got nil")
	}
	if !strings.Contains(err.Error(), "timed out") {
		t.Errorf("proxy timeout marker must force a timeout-shaped error: %s", err.Error())
	}
}

// TestExtractMCPResponseJSON_CommentsInterleavedDataWins: comment frames
// before/after a real data frame are ignored and the data payload is
// extracted intact.
func TestExtractMCPResponseJSON_CommentsInterleavedDataWins(t *testing.T) {
	body := []byte(": ping - 1\n\nevent: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"ok\":true}}\n\n: ping - 2\n\n")
	data, _, err := extractMCPResponseJSON(body, sseContentType, 30*time.Second, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	var resp MCPResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		t.Fatalf("extracted data is not valid JSON-RPC: %v\ndata: %s", err, data)
	}
	if resp.Result == nil {
		t.Errorf("expected result in extracted payload, got: %s", data)
	}
}

// TestExtractMCPResponseJSON_NormalSSEUnchanged: the plain happy path —
// event + data frame, no comments.
func TestExtractMCPResponseJSON_NormalSSEUnchanged(t *testing.T) {
	body := []byte("event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":\"hi\"}\n\n")
	data, _, err := extractMCPResponseJSON(body, sseContentType, time.Second, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if want := `{"jsonrpc":"2.0","id":1,"result":"hi"}`; string(data) != want {
		t.Errorf("got %q, want %q", data, want)
	}
}

// TestExtractMCPResponseJSON_PlainJSONPassthrough: non-SSE bodies are
// returned untouched regardless of elapsed time.
func TestExtractMCPResponseJSON_PlainJSONPassthrough(t *testing.T) {
	body := []byte(`{"jsonrpc":"2.0","id":1,"result":{"ok":true}}`)
	data, _, err := extractMCPResponseJSON(body, "application/json", time.Minute, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(data) != string(body) {
		t.Errorf("plain JSON body altered: got %q", data)
	}
}

// TestExtractMCPResponseJSON_SSEDetectionWithoutContentType: bodies that
// look like SSE are handled even when Content-Type is missing (some proxies
// strip it). Includes the comment-first body shape from sse-starlette.
func TestExtractMCPResponseJSON_SSEDetectionWithoutContentType(t *testing.T) {
	// data-first body, no content type
	data, _, err := extractMCPResponseJSON([]byte("data: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":1}\n\n"), "", time.Second, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(string(data), `"result":1`) {
		t.Errorf("data frame not extracted: %q", data)
	}

	// comment-only body, no content type — must still error, not pass through
	_, _, err = extractMCPResponseJSON([]byte(": ping - ts\n\n"), "", 30*time.Second, 30)
	if err == nil {
		t.Fatal("comment-only body without Content-Type must error, got nil")
	}
}

// TestSSEElapsedConsumedBudget pins the timeout-classification heuristic
// shared by the data-less and truncated-frame paths. The 1s slack only
// applies to budgets above 1s — for a 1s budget the slack would swallow the
// whole budget and classify ANY close (however fast) as a timeout.
func TestSSEElapsedConsumedBudget(t *testing.T) {
	cases := []struct {
		name           string
		elapsed        time.Duration
		timeoutSeconds int
		want           bool
	}{
		{"1s budget, quick close", 100 * time.Millisecond, 1, false},
		{"1s budget, just under", 999 * time.Millisecond, 1, false},
		{"1s budget, fully consumed", time.Second, 1, true},
		{"30s budget, within slack", 29 * time.Second, 30, true},
		{"30s budget, quick close", 5 * time.Second, 30, false},
		{"no budget", time.Hour, 0, false},
		{"negative budget", time.Hour, -5, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := sseElapsedConsumedBudget(c.elapsed, c.timeoutSeconds); got != c.want {
				t.Errorf("sseElapsedConsumedBudget(%v, %d) = %v, want %v", c.elapsed, c.timeoutSeconds, got, c.want)
			}
		})
	}
}

// TestExtractMCPResponseJSON_OneSecondBudgetQuickClose: with a 1s budget, a
// stream that closes almost immediately is a protocol error, not a timeout —
// the old budget−1s slack made the threshold zero and misclassified every
// quick close.
func TestExtractMCPResponseJSON_OneSecondBudgetQuickClose(t *testing.T) {
	body := []byte("event: message\n\n")
	_, _, err := extractMCPResponseJSON(body, sseContentType, 100*time.Millisecond, 1)
	if err == nil {
		t.Fatal("expected error for data-less SSE stream, got nil")
	}
	msg := err.Error()
	if strings.Contains(msg, "timed out") {
		t.Errorf("quick close on a 1s budget must not be reported as a timeout: %s", msg)
	}
	if !strings.Contains(msg, "without sending a response") {
		t.Errorf("protocol error missing explanation: %s", msg)
	}
}

// TestExtractMCPResponseJSON_NotificationThenResult: MCP streamable-HTTP may
// emit JSON-RPC notification frames (progress, logging) on the SAME stream
// before the terminal response. The notification must be skipped — it would
// unmarshal "successfully" into MCPResponse with nil Result/Error — and the
// terminal result frame returned.
func TestExtractMCPResponseJSON_NotificationThenResult(t *testing.T) {
	body := []byte("event: message\n" +
		"data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\",\"params\":{\"progressToken\":\"t\",\"message\":\"working...\"}}\n\n" +
		"event: message\n" +
		"data: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"ok\":true}}\n\n")
	data, fromSSE, err := extractMCPResponseJSON(body, sseContentType, time.Second, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !fromSSE {
		t.Error("expected fromSSE=true")
	}
	var resp MCPResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		t.Fatalf("extracted data is not valid JSON-RPC: %v\ndata: %s", err, data)
	}
	if resp.Result == nil {
		t.Errorf("expected the terminal result frame, got: %s", data)
	}
	if strings.Contains(string(data), "notifications/progress") {
		t.Errorf("notification frame returned instead of the response: %s", data)
	}
}

// TestExtractMCPResponseJSON_NotificationThenError: a terminal frame carrying
// a top-level "error" key is also the response — returned so the caller
// surfaces the JSON-RPC error.
func TestExtractMCPResponseJSON_NotificationThenError(t *testing.T) {
	body := []byte("data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\",\"params\":{\"level\":\"info\"}}\n\n" +
		"data: {\"jsonrpc\":\"2.0\",\"id\":1,\"error\":{\"code\":-32000,\"message\":\"boom\"}}\n\n")
	data, _, err := extractMCPResponseJSON(body, sseContentType, time.Second, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(string(data), "\"error\"") || strings.Contains(string(data), "notifications/message") {
		t.Errorf("expected the terminal error frame, got: %s", data)
	}
}

// TestExtractMCPResponseJSON_NotificationsOnlyErrors: a stream that carried
// only notification frames and then closed is still a no-response condition —
// it must error (mentioning the notifications), never return a notification
// frame as the "result".
func TestExtractMCPResponseJSON_NotificationsOnlyErrors(t *testing.T) {
	body := []byte("event: message\n" +
		"data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\",\"params\":{\"progressToken\":\"t\",\"message\":\"working...\"}}\n\n")
	_, _, err := extractMCPResponseJSON(body, sseContentType, 2*time.Second, 30)
	if err == nil {
		t.Fatal("expected error for notifications-only SSE stream, got nil")
	}
	msg := err.Error()
	if strings.Contains(msg, "timed out") {
		t.Errorf("quick notifications-only close must not be reported as a timeout: %s", msg)
	}
	if !strings.Contains(msg, "notification") {
		t.Errorf("error should mention that notification frames arrived: %s", msg)
	}
	if strings.Contains(msg, "working...") {
		t.Errorf("raw notification payload leaked into the error: %s", msg)
	}
}

// TestExtractMCPResponseJSON_NotificationThenTruncatedFrame: a notification
// followed by a cut-mid-payload response frame must surface the unparseable
// frame (so the caller routes to sseTruncatedFrameError), not the
// notification.
func TestExtractMCPResponseJSON_NotificationThenTruncatedFrame(t *testing.T) {
	partial := "{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"co"
	body := []byte("data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\",\"params\":{}}\n\n" +
		"data: " + partial + "\n")
	data, fromSSE, err := extractMCPResponseJSON(body, sseContentType, time.Second, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !fromSSE {
		t.Error("expected fromSSE=true")
	}
	if string(data) != partial {
		t.Errorf("expected the truncated frame back for downstream truncation handling, got: %s", data)
	}
}

// TestCallMCPTool_CommentOnlySSEErrors wires the extraction through the full
// callMCPTool path: an agent answering only a keepalive comment must produce
// an error, not the comment text as a successful result.
func TestCallMCPTool_CommentOnlySSEErrors(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte(": ping - 2026-06-09 12:00:00+00:00\r\n\r\n"))
	}))
	defer srv.Close()

	result, err := callMCPTool(http.DefaultClient, srv.URL, "slow_tool", map[string]interface{}{}, nil, nil, 30)
	if err == nil {
		t.Fatalf("expected error for comment-only SSE response, got result: %+v", result)
	}
	if strings.Contains(err.Error(), "ping") {
		t.Errorf("keepalive comment leaked into error: %s", err.Error())
	}
}

// TestCallMCPTool_SSEWithCommentsStillSucceeds is the happy-path guard for
// the full call path: keepalive comments around a real data frame don't
// disturb the result.
func TestCallMCPTool_SSEWithCommentsStillSucceeds(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte(": ping - keepalive\n\nevent: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"ok\":true}}\n\n"))
	}))
	defer srv.Close()

	result, err := callMCPTool(http.DefaultClient, srv.URL, "slow_tool", map[string]interface{}{}, nil, nil, 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(string(result.Result), `"ok":true`) {
		t.Errorf("unexpected result payload: %s", result.Result)
	}
}

// TestCallMCPTool_TruncatedDataFrameWithMarkerIsTimeout covers the
// mid-data-frame cut: the proxy's X-Mesh-Timeout budget fires while the
// result frame is in flight, leaving a partial `data:` payload followed by
// the terminal timeout marker. The extracted frame fails to parse — that must
// be a timeout-shaped error (the marker is in the body), NEVER the raw SSE
// envelope returned as a successful result with exit 0.
func TestCallMCPTool_TruncatedDataFrameWithMarkerIsTimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"res\n: mesh-proxy-timeout budget=30s\n\n"))
	}))
	defer srv.Close()

	result, err := callMCPTool(http.DefaultClient, srv.URL, "slow_tool", map[string]interface{}{}, nil, nil, 30)
	if err == nil {
		t.Fatalf("expected error for truncated SSE data frame, got result: %s", result.Result)
	}
	msg := err.Error()
	if !strings.Contains(msg, "timed out") {
		t.Errorf("marker in body must force a timeout-shaped error: %s", msg)
	}
	if !strings.Contains(msg, "--timeout") {
		t.Errorf("timeout error missing the --timeout remedy: %s", msg)
	}
	if strings.Contains(msg, "mesh-proxy-timeout") || strings.Contains(msg, `"jsonrpc"`) {
		t.Errorf("raw SSE envelope leaked into the error: %s", msg)
	}
}

// TestCallMCPTool_TruncatedDataFrameQuickCloseIsProtocolError: a partial data
// frame with NO marker and the stream closed well within the budget is the
// agent (or an intermediary) misbehaving — a protocol error, not a timeout,
// and never the raw body as success.
func TestCallMCPTool_TruncatedDataFrameQuickCloseIsProtocolError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"res"))
	}))
	defer srv.Close()

	result, err := callMCPTool(http.DefaultClient, srv.URL, "slow_tool", map[string]interface{}{}, nil, nil, 30)
	if err == nil {
		t.Fatalf("expected error for truncated SSE data frame, got result: %s", result.Result)
	}
	msg := err.Error()
	if strings.Contains(msg, "timed out") {
		t.Errorf("quick truncated frame must not be reported as a timeout: %s", msg)
	}
	if !strings.Contains(msg, "truncated or invalid SSE data frame") {
		t.Errorf("protocol error missing truncation explanation: %s", msg)
	}
}

// TestCallMCPTool_NonSSEPlainTextFallbackUnchanged: the raw-body fallback for
// non-JSON-RPC responses survives for non-SSE bodies only (legacy plain-text
// agents) — those still come back verbatim as a successful result.
func TestCallMCPTool_NonSSEPlainTextFallbackUnchanged(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		_, _ = w.Write([]byte("hello from a legacy agent"))
	}))
	defer srv.Close()

	result, err := callMCPTool(http.DefaultClient, srv.URL, "legacy_tool", map[string]interface{}{}, nil, nil, 30)
	if err != nil {
		t.Fatalf("unexpected error for plain-text body: %v", err)
	}
	if string(result.Result) != "hello from a legacy agent" {
		t.Errorf("plain-text fallback altered the body: %q", result.Result)
	}
}

// TestAuditShortIsHelpful covers issue #956 item #22: the audit command's
// Short text must convey when a user would reach for it (routing/why).
func TestAuditShortIsHelpful(t *testing.T) {
	cmd := NewAuditCommand()
	if cmd.Short == "" {
		t.Fatal("audit command has empty Short")
	}
	// Heuristic: the new wording must mention either "routed" or "route"
	// so users searching for routing/dispatch find it.
	low := strings.ToLower(cmd.Short)
	if !strings.Contains(low, "rout") {
		t.Errorf("audit Short does not convey routing context: %q", cmd.Short)
	}
}

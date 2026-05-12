package cli

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
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

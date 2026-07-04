package registry

// Tests for proxyRequest's baked-in default header forwarding at the
// registry agent-proxy hop. These headers are forwarded WITHOUT the operator
// opting in via MCP_MESH_PROPAGATE_HEADERS so registry-proxied topologies keep
// the calling-job identity feature (#1263) working out of the box. The pair is
// forwarded atomically: each header is forwarded only if it actually arrived —
// never synthesized.

import (
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// registerProxyTargetAgent registers an agent whose HTTP endpoint points at the
// given host:port (typically a downstream httptest server) so proxyRequest's
// isRegisteredAgentEndpoint validation passes and the call is forwarded.
func registerProxyTargetAgent(t *testing.T, s *EntService, agentID, host string, port int) {
	t.Helper()
	req := &AgentRegistrationRequest{
		AgentID: agentID,
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       agentID,
			"http_host":  host,
			"http_port":  port,
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "echo_fn",
					"capability":    "echo",
					"version":       "1.0.0",
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	if _, err := s.RegisterAgent(req); err != nil {
		t.Fatalf("RegisterAgent(%s): %v", agentID, err)
	}
}

// newProxyDownstream starts a downstream server that records the headers it
// received and returns (server, *received). host/port are the dial coordinates
// to register as the proxy target.
func newProxyDownstream(t *testing.T, received *http.Header) (*httptest.Server, string, int) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*received = r.Header.Clone()
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, `{"ok":true}`)
	}))
	host, portStr, err := net.SplitHostPort(strings.TrimPrefix(srv.URL, "http://"))
	if err != nil {
		srv.Close()
		t.Fatalf("SplitHostPort(%s): %v", srv.URL, err)
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		srv.Close()
		t.Fatalf("Atoi(%s): %v", portStr, err)
	}
	return srv, host, port
}

func proxyPost(t *testing.T, h *EntBusinessLogicHandlers, target string, headers map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	req := httptest.NewRequest("POST", "/mcp/v1/tools/call", strings.NewReader("{}"))
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	c.Request = req
	h.proxyRequest(c, target, "POST")
	return w
}

// TestProxyRequest_ForwardsCallingJobIdentityPair asserts the calling-job
// identity pair (and the existing X-Mesh-Job-Id default) are forwarded at the
// proxy hop with no MCP_MESH_PROPAGATE_HEADERS opt-in.
func TestProxyRequest_ForwardsCallingJobIdentityPair(t *testing.T) {
	gin.SetMode(gin.TestMode)
	s := setupTestService(t)

	var received http.Header
	srv, host, port := newProxyDownstream(t, &received)
	defer srv.Close()

	registerProxyTargetAgent(t, s, "echo-agent", host, port)
	h := &EntBusinessLogicHandlers{entService: s}

	target := host + ":" + strconv.Itoa(port) + "/mcp/v1/tools/call"
	w := proxyPost(t, h, target, map[string]string{
		"X-Mesh-Job-Id":              "job-123",
		"X-Mesh-Calling-Job-Id":      "caller-777",
		"X-Mesh-Calling-Claim-Epoch": "5",
	})

	if w.Code != http.StatusOK {
		t.Fatalf("proxy returned %d, body=%s", w.Code, w.Body.String())
	}
	if got := received.Get("X-Mesh-Job-Id"); got != "job-123" {
		t.Errorf("X-Mesh-Job-Id not forwarded: got %q", got)
	}
	if got := received.Get("X-Mesh-Calling-Job-Id"); got != "caller-777" {
		t.Errorf("X-Mesh-Calling-Job-Id not forwarded: got %q", got)
	}
	if got := received.Get("X-Mesh-Calling-Claim-Epoch"); got != "5" {
		t.Errorf("X-Mesh-Calling-Claim-Epoch not forwarded: got %q", got)
	}
}

// TestProxyRequest_ForwardsPartialCallingIdentity asserts the pair is forwarded
// atomically as "forward what arrived": when only X-Mesh-Calling-Job-Id is
// present, the epoch header is NOT synthesized.
func TestProxyRequest_ForwardsPartialCallingIdentity(t *testing.T) {
	gin.SetMode(gin.TestMode)
	s := setupTestService(t)

	var received http.Header
	srv, host, port := newProxyDownstream(t, &received)
	defer srv.Close()

	registerProxyTargetAgent(t, s, "echo-agent", host, port)
	h := &EntBusinessLogicHandlers{entService: s}

	target := host + ":" + strconv.Itoa(port) + "/mcp/v1/tools/call"
	w := proxyPost(t, h, target, map[string]string{
		"X-Mesh-Calling-Job-Id": "caller-777",
	})

	if w.Code != http.StatusOK {
		t.Fatalf("proxy returned %d, body=%s", w.Code, w.Body.String())
	}
	if got := received.Get("X-Mesh-Calling-Job-Id"); got != "caller-777" {
		t.Errorf("X-Mesh-Calling-Job-Id not forwarded: got %q", got)
	}
	if got := received.Get("X-Mesh-Calling-Claim-Epoch"); got != "" {
		t.Errorf("X-Mesh-Calling-Claim-Epoch synthesized when absent: got %q", got)
	}
}

package registry

// Issue #1583: proxy targets were split on ":" with a hard len(parts) == 2
// check, so an IPv6-literal target ("[::1]:8080") parsed as five fields and
// was rejected as malformed before any lookup happened — an IPv6-only
// cluster could never proxy to any agent.

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"github.com/gin-gonic/gin"
)

// newIPv6Downstream starts a downstream agent bound to the IPv6 loopback.
// Skips the test where IPv6 loopback is unavailable.
func newIPv6Downstream(t *testing.T) (*httptest.Server, string, int) {
	t.Helper()
	l, err := net.Listen("tcp", "[::1]:0")
	if err != nil {
		t.Skipf("IPv6 loopback unavailable: %v", err)
	}
	srv := &httptest.Server{
		Listener: l,
		Config: &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"ok":true}`))
		})},
	}
	srv.Start()
	return srv, "::1", l.Addr().(*net.TCPAddr).Port
}

func TestIsRegisteredAgentEndpoint_AcceptsIPv6Literal(t *testing.T) {
	gin.SetMode(gin.TestMode)
	s := setupTestService(t)
	registerProxyTargetAgent(t, s, "v6-agent", "::1", 9443)

	h := &EntBusinessLogicHandlers{entService: s}
	ok, scheme, endpointHost, err := h.isRegisteredAgentEndpoint(context.Background(), "[::1]:9443")
	if err != nil {
		t.Fatalf("isRegisteredAgentEndpoint: %v", err)
	}
	if !ok {
		t.Fatal("IPv6-literal target was not recognised as a registered agent")
	}
	if scheme != "http" {
		t.Errorf("scheme = %q, want http", scheme)
	}
	// The dial host has to come back bracketed or the URL the proxy builds
	// from it ("http://::1:9443/mcp") is unparseable.
	if endpointHost != "[::1]:9443" {
		t.Errorf("endpointHost = %q, want %q", endpointHost, "[::1]:9443")
	}
}

func TestIsRegisteredAgentEndpoint_RejectsMalformedTargets(t *testing.T) {
	gin.SetMode(gin.TestMode)
	s := setupTestService(t)
	h := &EntBusinessLogicHandlers{entService: s}

	for _, target := range []string{"nohost", "host:", ":8080", "host:notaport", "host:0", "[::1]"} {
		ok, _, _, err := h.isRegisteredAgentEndpoint(context.Background(), target)
		if err != nil {
			t.Fatalf("isRegisteredAgentEndpoint(%q): %v", target, err)
		}
		if ok {
			t.Errorf("target %q was accepted, want rejected", target)
		}
	}
}

// TestProxyRequest_ForwardsToIPv6Agent is the end-to-end case: a real
// request proxied to an agent listening on the IPv6 loopback.
func TestProxyRequest_ForwardsToIPv6Agent(t *testing.T) {
	gin.SetMode(gin.TestMode)
	s := setupTestService(t)

	downstream, host, port := newIPv6Downstream(t)
	defer downstream.Close()

	registerProxyTargetAgent(t, s, "v6-agent", host, port)
	h := &EntBusinessLogicHandlers{entService: s}

	target := net.JoinHostPort(host, strconv.Itoa(port)) + "/mcp/v1/tools/call"
	w := proxyPost(t, h, target, nil)

	if w.Code != http.StatusOK {
		t.Fatalf("proxy to IPv6 agent returned %d, body=%s", w.Code, w.Body.String())
	}
}

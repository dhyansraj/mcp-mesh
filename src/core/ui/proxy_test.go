package ui

// Issue #1583: proxyToRegistry read the registry response through a
// LimitReader at 10MB and forwarded whatever it got with the upstream's
// status code. A response over the cap therefore reached the browser as
// JSON cut mid-token, carrying a 200 — indistinguishable from a valid
// reply until it failed to parse.

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// newProxyTestServer wires a UI server at an upstream registry stub.
func newProxyTestServer(t *testing.T, registryURL string) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)

	s := &Server{
		config:     &UIConfig{RegistryURL: registryURL},
		httpClient: &http.Client{},
	}

	e := gin.New()
	e.GET("/api/*path", s.proxyToRegistry)
	return e
}

func TestProxyToRegistry_ForwardsNormalResponse(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, `{"agents":[]}`)
	}))
	defer upstream.Close()

	srv := httptest.NewServer(newProxyTestServer(t, upstream.URL))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/agents")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
	}
	if string(body) != `{"agents":[]}` {
		t.Errorf("body = %s, want the upstream document verbatim", body)
	}
}

// TestProxyToRegistry_OverlargeResponseIs502 is the fix: a response past
// the cap must fail the request rather than forward a truncated body.
func TestProxyToRegistry_OverlargeResponseIs502(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		// A valid JSON document that is one byte past the cap. Truncating
		// it produces the exact failure mode being fixed: parseable-looking
		// prefix, no closing quote or brace.
		_, _ = io.WriteString(w, `{"pad":"`)
		_, _ = io.WriteString(w, strings.Repeat("x", int(maxRegistryResponseBytes)))
		_, _ = io.WriteString(w, `"}`)
	}))
	defer upstream.Close()

	srv := httptest.NewServer(newProxyTestServer(t, upstream.URL))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/agents")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502 (a truncated body must not be forwarded with the upstream status); body length %d",
			resp.StatusCode, len(body))
	}

	// The failure must itself be well-formed JSON — the whole point is
	// that the client can tell what happened.
	var parsed map[string]interface{}
	if err := json.Unmarshal(body, &parsed); err != nil {
		t.Fatalf("502 body is not valid JSON (%v): %s", err, body)
	}
	if msg, _ := parsed["error"].(string); !strings.Contains(msg, "exceeded") {
		t.Errorf("502 body does not explain the truncation: %s", body)
	}
}

// TestProxyToRegistry_ResponseExactlyAtLimitIsForwarded pins the boundary:
// the cap is inclusive, so a document exactly at the limit is still a
// complete document and must be served.
func TestProxyToRegistry_ResponseExactlyAtLimitIsForwarded(t *testing.T) {
	padding := int(maxRegistryResponseBytes) - len(`{"pad":""}`)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"pad":"`+strings.Repeat("x", padding)+`"}`)
	}))
	defer upstream.Close()

	srv := httptest.NewServer(newProxyTestServer(t, upstream.URL))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/agents")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200 for a document exactly at the limit", resp.StatusCode)
	}
	if int64(len(body)) != maxRegistryResponseBytes {
		t.Errorf("forwarded %d bytes, want %d", len(body), maxRegistryResponseBytes)
	}
	var parsed map[string]interface{}
	if err := json.Unmarshal(body, &parsed); err != nil {
		t.Fatalf("forwarded body is not valid JSON: %v", err)
	}
}

func TestProxyToRegistry_UnreachableRegistryIs502(t *testing.T) {
	// Port 1 on loopback: nothing listens there.
	srv := httptest.NewServer(newProxyTestServer(t, "http://127.0.0.1:1"))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/agents")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", resp.StatusCode)
	}
}

package registry

// Coverage for the listener hardening in issue #1583: the connection
// limits every registry listener now carries, and the request-body cap
// that fronts every JSON handler.

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestNewHardenedServer_SetsConnectionLimits(t *testing.T) {
	srv := newHardenedServer(":8000", gin.New())

	if srv.ReadHeaderTimeout != defaultReadHeaderTimeout {
		t.Errorf("ReadHeaderTimeout = %v, want %v", srv.ReadHeaderTimeout, defaultReadHeaderTimeout)
	}
	if srv.IdleTimeout != defaultIdleTimeout {
		t.Errorf("IdleTimeout = %v, want %v", srv.IdleTimeout, defaultIdleTimeout)
	}
	if srv.MaxHeaderBytes != defaultMaxHeaderBytes {
		t.Errorf("MaxHeaderBytes = %d, want %d", srv.MaxHeaderBytes, defaultMaxHeaderBytes)
	}

	// ReadTimeout and WriteTimeout are deliberately unset: both would cut
	// the 60s job-event long-poll and the unbounded SSE relay through
	// /proxy/*. If someone sets them, that is the regression to catch.
	if srv.ReadTimeout != 0 {
		t.Errorf("ReadTimeout = %v, want 0 (would cap slow uploads and long-polls)", srv.ReadTimeout)
	}
	if srv.WriteTimeout != 0 {
		t.Errorf("WriteTimeout = %v, want 0 (would sever proxied SSE streams)", srv.WriteTimeout)
	}
}

func TestMaxRequestBodyBytesFromEnv(t *testing.T) {
	tests := []struct {
		name string
		set  bool
		val  string
		want int64
	}{
		{name: "unset uses default", want: defaultMaxRequestBodyBytes},
		{name: "override", set: true, val: "1048576", want: 1048576},
		{name: "zero disables", set: true, val: "0", want: 0},
		{name: "negative falls back", set: true, val: "-1", want: defaultMaxRequestBodyBytes},
		{name: "garbage falls back", set: true, val: "10MB", want: defaultMaxRequestBodyBytes},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if tc.set {
				t.Setenv("MCP_MESH_MAX_REQUEST_BODY_BYTES", tc.val)
			} else {
				t.Setenv("MCP_MESH_MAX_REQUEST_BODY_BYTES", "")
			}
			if got := maxRequestBodyBytesFromEnv(); got != tc.want {
				t.Errorf("maxRequestBodyBytesFromEnv() = %d, want %d", got, tc.want)
			}
		})
	}
}

// bindEngine mirrors the real handler shape: the body cap middleware in
// front of a handler that binds JSON and reports errors through
// writeBindError.
func bindEngine(limit int64) *gin.Engine {
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(MaxRequestBodyMiddleware(limit))
	e.POST("/bind", func(c *gin.Context) {
		var body map[string]interface{}
		if err := c.ShouldBindJSON(&body); err != nil {
			writeBindError(c, err)
			return
		}
		c.JSON(http.StatusOK, gin.H{"fields": len(body)})
	})
	return e
}

// oversizedJSON returns a syntactically valid JSON object of at least n bytes.
func oversizedJSON(n int) string {
	var b strings.Builder
	b.WriteString(`{"pad":"`)
	b.WriteString(strings.Repeat("x", n))
	b.WriteString(`"}`)
	return b.String()
}

// unknownLengthBody hides its size from the http client so the request
// goes out chunked with ContentLength -1, bypassing the Content-Length
// pre-check and exercising the MaxBytesReader layer.
type unknownLengthBody struct{ r io.Reader }

func (u unknownLengthBody) Read(p []byte) (int, error) { return u.r.Read(p) }
func (u unknownLengthBody) Close() error               { return nil }

func TestMaxRequestBodyMiddleware_DeclaredLengthOverLimitIs413(t *testing.T) {
	srv := httptest.NewServer(bindEngine(1024))
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/bind", "application/json", strings.NewReader(oversizedJSON(4096)))
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusRequestEntityTooLarge {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 413; body=%s", resp.StatusCode, body)
	}

	// The rejection must be a well-formed error document, not a bare
	// status or a panic-recovery 500.
	var parsed map[string]interface{}
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &parsed); err != nil {
		t.Fatalf("413 body is not JSON (%v): %s", err, body)
	}
	if msg, _ := parsed["error"].(string); !strings.Contains(msg, "MCP_MESH_MAX_REQUEST_BODY_BYTES") {
		t.Errorf("413 body does not name the knob to raise: %s", body)
	}
}

func TestMaxRequestBodyMiddleware_UndeclaredLengthOverLimitIs413(t *testing.T) {
	srv := httptest.NewServer(bindEngine(1024))
	defer srv.Close()

	req, err := http.NewRequest("POST", srv.URL+"/bind", unknownLengthBody{strings.NewReader(oversizedJSON(4096))})
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if req.ContentLength != 0 {
		t.Fatalf("test setup: expected an unknown-length body, got ContentLength=%d", req.ContentLength)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusRequestEntityTooLarge {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 413; body=%s", resp.StatusCode, body)
	}
}

func TestMaxRequestBodyMiddleware_UnderLimitPasses(t *testing.T) {
	srv := httptest.NewServer(bindEngine(1 << 20))
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/bind", "application/json", strings.NewReader(`{"a":1,"b":2}`))
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
	}
}

func TestMaxRequestBodyMiddleware_MalformedJSONStillIs400(t *testing.T) {
	srv := httptest.NewServer(bindEngine(1 << 20))
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/bind", "application/json", strings.NewReader(`{"a":`))
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", resp.StatusCode)
	}
	body, _ := io.ReadAll(resp.Body)
	if !strings.Contains(string(body), "Invalid JSON payload") {
		t.Errorf("400 message changed shape: %s", body)
	}
}

func TestMaxRequestBodyMiddleware_ZeroLimitDisablesTheCap(t *testing.T) {
	srv := httptest.NewServer(bindEngine(0))
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/bind", "application/json", strings.NewReader(oversizedJSON(2<<20)))
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200 with the cap disabled", resp.StatusCode)
	}
}

// TestHeartbeat_OversizedBodyIs413 exercises the real registration
// handler behind the real middleware: an over-limit heartbeat must be
// refused as 413 rather than being buffered and answered 400/500.
func TestHeartbeat_OversizedBodyIs413(t *testing.T) {
	gin.SetMode(gin.TestMode)
	service := setupTestService(t)
	handlers := &EntBusinessLogicHandlers{entService: service}

	engine := gin.New()
	engine.Use(MaxRequestBodyMiddleware(64 << 10))
	engine.POST("/heartbeat", handlers.SendHeartbeat)

	srv := httptest.NewServer(engine)
	defer srv.Close()

	// A registration payload whose tool description alone blows the cap.
	payload := fmt.Sprintf(`{"agent_id":"big-agent","tools":[{"capability":"c","function_name":"f","description":"%s"}]}`,
		strings.Repeat("d", 128<<10))

	resp, err := http.Post(srv.URL+"/heartbeat", "application/json", strings.NewReader(payload))
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusRequestEntityTooLarge {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 413; body=%s", resp.StatusCode, body)
	}
}

// TestHeartbeat_LargeButLegalBodyIsAccepted pins the other side of the
// limit: the default cap must not reject a heartbeat from a genuinely
// large agent. ~100 tools of realistic size is well under 10MB.
func TestHeartbeat_LargeButLegalBodyIsAccepted(t *testing.T) {
	gin.SetMode(gin.TestMode)
	service := setupTestService(t)
	handlers := &EntBusinessLogicHandlers{entService: service}

	engine := gin.New()
	engine.Use(MaxRequestBodyMiddleware(defaultMaxRequestBodyBytes))
	engine.POST("/heartbeat", handlers.SendHeartbeat)

	srv := httptest.NewServer(engine)
	defer srv.Close()

	tools := make([]string, 0, 100)
	for i := 0; i < 100; i++ {
		tools = append(tools, fmt.Sprintf(
			`{"capability":"cap_%d","function_name":"fn_%d","description":"%s","inputSchema":{"type":"object","properties":{"a":{"type":"string","description":"%s"}}}}`,
			i, i, strings.Repeat("d", 200), strings.Repeat("p", 200)))
	}
	payload := fmt.Sprintf(`{"agent_id":"large-agent","http_host":"localhost","http_port":9100,"tools":[%s]}`,
		strings.Join(tools, ","))
	if len(payload) < 50_000 {
		t.Fatalf("test setup: payload only %d bytes, not exercising size", len(payload))
	}

	resp, err := http.Post(srv.URL+"/heartbeat", "application/json", strings.NewReader(payload))
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusRequestEntityTooLarge {
		t.Fatalf("a %d byte heartbeat was rejected by the %d byte default cap",
			len(payload), defaultMaxRequestBodyBytes)
	}
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
	}
}

// TestMaxRequestBodyMiddleware_DoesNotDelayStreamingReads guards the
// intent behind leaving ReadTimeout unset: a handler that holds the
// request open (long-poll shape) is not affected by the body cap.
func TestMaxRequestBodyMiddleware_DoesNotDelayStreamingReads(t *testing.T) {
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(MaxRequestBodyMiddleware(1024))
	e.GET("/poll", func(c *gin.Context) {
		time.Sleep(150 * time.Millisecond)
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	srv := httptest.NewServer(e)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/poll")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
}

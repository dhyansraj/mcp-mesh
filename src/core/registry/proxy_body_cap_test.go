package registry

// Tests for issue #1608: how /proxy/* applies the request-body cap.
// A chunked body is buffered up to the cap and refused with 413 before
// anything reaches the agent; a declared-length body (already bounded by
// the middleware's pre-check) and any body with the cap disabled keep
// streaming.

import (
	"bytes"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// bodyRecordingAgent is a downstream agent that records every body it is
// sent. If firstChunk > 0 it reads that many bytes, signals gotFirst, and
// only then reads the rest — which lets a test prove the registry
// forwarded the start of a body before the client had finished sending it.
type bodyRecordingAgent struct {
	mu         sync.Mutex
	requests   int
	bodies     [][]byte
	contentLen []int64
	firstChunk int
	gotFirst   chan struct{}
}

func (a *bodyRecordingAgent) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var body []byte
	if a.firstChunk > 0 {
		head := make([]byte, a.firstChunk)
		if _, err := io.ReadFull(r.Body, head); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		close(a.gotFirst)
		rest, _ := io.ReadAll(r.Body)
		body = append(head, rest...)
	} else {
		body, _ = io.ReadAll(r.Body)
	}
	a.mu.Lock()
	a.requests++
	a.bodies = append(a.bodies, body)
	a.contentLen = append(a.contentLen, r.ContentLength)
	a.mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	_, _ = io.WriteString(w, `{"ok":true}`)
}

func (a *bodyRecordingAgent) snapshot() (int, [][]byte, []int64) {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.requests, append([][]byte(nil), a.bodies...), append([]int64(nil), a.contentLen...)
}

// newCappedProxy serves POST /proxy/*target behind MaxRequestBodyMiddleware
// at limit, forwarding to a registered agent backed by agent. Returns the
// registry's base URL and the proxy path for that agent.
func newCappedProxy(t *testing.T, limit int64, agent http.Handler) (string, string) {
	t.Helper()
	downstream := httptest.NewServer(agent)
	t.Cleanup(downstream.Close)
	host, portStr, err := net.SplitHostPort(strings.TrimPrefix(downstream.URL, "http://"))
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(portStr)

	service := setupTestService(t)
	registerProxyTargetAgent(t, service, "body-agent", host, port)
	h := NewEntBusinessLogicHandlers(service)

	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(MaxRequestBodyMiddleware(limit))
	e.POST("/proxy/*target", func(c *gin.Context) {
		h.ProxyMcpRequest(c, strings.TrimPrefix(c.Param("target"), "/"))
	})
	registry := httptest.NewServer(e)
	t.Cleanup(registry.Close)
	return registry.URL, "/proxy/" + net.JoinHostPort(host, portStr) + "/mcp"
}

func postChunked(t *testing.T, url string, body []byte) *http.Response {
	t.Helper()
	req, err := http.NewRequest("POST", url, unknownLengthBody{bytes.NewReader(body)})
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	if req.ContentLength != 0 {
		t.Fatalf("test setup: expected an unknown-length body, got ContentLength=%d", req.ContentLength)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	return resp
}

func TestProxy_ChunkedBodyOverCapIs413AndNeverReachesAgent(t *testing.T) {
	agent := &bodyRecordingAgent{}
	base, path := newCappedProxy(t, 1024, agent)

	resp := postChunked(t, base+path, []byte(oversizedJSON(4096)))
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413; body=%s", resp.StatusCode, body)
	}
	if !strings.Contains(string(body), "MCP_MESH_MAX_REQUEST_BODY_BYTES") {
		t.Errorf("413 body does not name the knob to raise: %s", body)
	}
	if n, _, _ := agent.snapshot(); n != 0 {
		t.Fatalf("agent received %d request(s); an over-cap body must not reach it at all", n)
	}
}

func TestProxy_ChunkedBodyUnderCapIsForwardedIntact(t *testing.T) {
	agent := &bodyRecordingAgent{}
	base, path := newCappedProxy(t, 1024, agent)

	payload := []byte(oversizedJSON(900))
	resp := postChunked(t, base+path, payload)
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
	}

	n, bodies, lens := agent.snapshot()
	if n != 1 {
		t.Fatalf("agent received %d requests, want 1", n)
	}
	if !bytes.Equal(bodies[0], payload) {
		t.Fatalf("agent received %d bytes, want the %d-byte payload intact", len(bodies[0]), len(payload))
	}
	// Buffered, so it is forwarded with a known length.
	if lens[0] != int64(len(payload)) {
		t.Errorf("agent saw Content-Length %d, want %d", lens[0], len(payload))
	}
}

// TestProxy_ChunkedBodyExactlyAtCapIsForwarded pins the boundary: a body of
// exactly limit bytes is legal.
func TestProxy_ChunkedBodyExactlyAtCapIsForwarded(t *testing.T) {
	agent := &bodyRecordingAgent{}
	base, path := newCappedProxy(t, 1024, agent)

	payload := bytes.Repeat([]byte("x"), 1024)
	resp := postChunked(t, base+path, payload)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
	}
	if _, bodies, _ := agent.snapshot(); len(bodies) != 1 || len(bodies[0]) != 1024 {
		t.Fatalf("agent did not receive the 1024-byte body intact")
	}
}

// postStreamed sends total bytes through a pipe in two halves and only sends
// the second half once the agent has received the first. A proxy that
// buffered the whole body would never forward the first half on its own, so
// the agent would never signal and the test times out.
func postStreamed(t *testing.T, url string, total int, declareLength bool, agent *bodyRecordingAgent) *http.Response {
	t.Helper()
	pr, pw := io.Pipe()
	req, err := http.NewRequest("POST", url, pr)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	if declareLength {
		req.ContentLength = int64(total)
	}

	type result struct {
		resp *http.Response
		err  error
	}
	done := make(chan result, 1)
	go func() {
		resp, err := http.DefaultClient.Do(req)
		done <- result{resp, err}
	}()

	half := total / 2
	if _, err := pw.Write(bytes.Repeat([]byte("a"), half)); err != nil {
		t.Fatalf("write first half: %v", err)
	}
	select {
	case <-agent.gotFirst:
	case <-time.After(5 * time.Second):
		_ = pw.CloseWithError(io.ErrUnexpectedEOF)
		t.Fatal("agent never received the first half while the client was still sending: the proxy buffered instead of streaming")
	}
	if _, err := pw.Write(bytes.Repeat([]byte("b"), total-half)); err != nil {
		t.Fatalf("write second half: %v", err)
	}
	_ = pw.Close()

	r := <-done
	if r.err != nil {
		t.Fatalf("POST: %v", r.err)
	}
	return r.resp
}

func TestProxy_DeclaredLengthUnderCapStillStreams(t *testing.T) {
	const total = 256 << 10
	agent := &bodyRecordingAgent{firstChunk: total / 2, gotFirst: make(chan struct{})}
	base, path := newCappedProxy(t, 1<<20, agent)

	resp := postStreamed(t, base+path, total, true, agent)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
	}
	_, bodies, lens := agent.snapshot()
	if len(bodies) != 1 || len(bodies[0]) != total {
		t.Fatalf("agent did not receive the %d-byte body", total)
	}
	// Streamed, but still carrying the caller's declared length.
	if lens[0] != int64(total) {
		t.Errorf("agent saw Content-Length %d, want the declared %d (not chunked)", lens[0], total)
	}
}

// TestProxy_DeclaredLengthIsForwarded pins that a declared-length proxied
// POST reaches the agent with its Content-Length, as the caller sent it,
// rather than re-encoded as chunked — with the cap on and with it off.
func TestProxy_DeclaredLengthIsForwarded(t *testing.T) {
	for _, limit := range []int64{1 << 20, 0} {
		t.Run("limit="+strconv.FormatInt(limit, 10), func(t *testing.T) {
			agent := &bodyRecordingAgent{}
			base, path := newCappedProxy(t, limit, agent)

			payload := oversizedJSON(900)
			resp, err := http.Post(base+path, "application/json", strings.NewReader(payload))
			if err != nil {
				t.Fatalf("POST: %v", err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				body, _ := io.ReadAll(resp.Body)
				t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
			}
			_, bodies, lens := agent.snapshot()
			if len(bodies) != 1 || string(bodies[0]) != payload {
				t.Fatalf("agent did not receive the payload intact")
			}
			if lens[0] != int64(len(payload)) {
				t.Errorf("agent saw Content-Length %d, want %d", lens[0], len(payload))
			}
		})
	}
}

// TestProxy_CapDisabledChunkedStreamsUnbounded pins that
// MCP_MESH_MAX_REQUEST_BODY_BYTES=0 keeps the proxy streaming: nothing is
// buffered and nothing is capped.
func TestProxy_CapDisabledChunkedStreamsUnbounded(t *testing.T) {
	const total = 256 << 10
	agent := &bodyRecordingAgent{firstChunk: total / 2, gotFirst: make(chan struct{})}
	base, path := newCappedProxy(t, 0, agent)

	resp := postStreamed(t, base+path, total, false, agent)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 200; body=%s", resp.StatusCode, body)
	}
	if _, bodies, _ := agent.snapshot(); len(bodies) != 1 || len(bodies[0]) != total {
		t.Fatalf("agent did not receive the %d-byte body", total)
	}
}

package registry

// Coverage for issue #1606's proxy half: on shutdown a proxied GET stream
// (an MCP SSE subscription, no in-flight work) is cut so it does not hold
// the HTTP drain open, while a proxied POST (a tool call, possibly
// streaming its result) is left to finish.

import (
	"bufio"
	"bytes"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

// newSSEProxy fronts an agent whose /mcp endpoint streams one SSE event and
// then holds the stream open until release is closed (or the request is
// cancelled), then sends a final event.
func newSSEProxy(t *testing.T, release <-chan struct{}) (*EntService, string, string) {
	t.Helper()
	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "event: first\ndata: {}\n\n")
		w.(http.Flusher).Flush()
		select {
		case <-release:
			_, _ = io.WriteString(w, "event: last\ndata: {}\n\n")
		case <-r.Context().Done():
		}
	}))
	t.Cleanup(agent.Close)
	host, portStr, err := net.SplitHostPort(strings.TrimPrefix(agent.URL, "http://"))
	require.NoError(t, err)
	port, _ := strconv.Atoi(portStr)

	service := setupTestService(t)
	registerProxyTargetAgent(t, service, "sse-agent", host, port)
	h := NewEntBusinessLogicHandlers(service)

	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.GET("/proxy/*target", func(c *gin.Context) { h.ProxyMcpGetRequest(c, strings.TrimPrefix(c.Param("target"), "/")) })
	e.POST("/proxy/*target", func(c *gin.Context) { h.ProxyMcpRequest(c, strings.TrimPrefix(c.Param("target"), "/")) })
	registry := httptest.NewServer(e)
	t.Cleanup(registry.Close)
	return service, registry.URL, "/proxy/" + net.JoinHostPort(host, portStr) + "/mcp"
}

// readRest drains body in the background and reports what it read.
func readRest(r io.Reader) <-chan string {
	out := make(chan string, 1)
	go func() {
		b, _ := io.ReadAll(r)
		out <- string(b)
	}()
	return out
}

func TestProxy_ShutdownCutsGetStream(t *testing.T) {
	release := make(chan struct{})
	defer close(release)
	service, base, path := newSSEProxy(t, release)

	resp, err := http.Get(base + path)
	require.NoError(t, err)
	defer resp.Body.Close()
	reader := bufio.NewReader(resp.Body)
	line, err := reader.ReadString('\n')
	require.NoError(t, err)
	require.Equal(t, "event: first\n", line)

	rest := readRest(reader)
	service.BeginShutdown()
	select {
	case <-rest:
	case <-time.After(2 * time.Second):
		t.Fatal("proxied GET stream still open after BeginShutdown")
	}
}

// relayLog captures the registry's relay log lines for a failure message.
type relayLog struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (l *relayLog) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.buf.Write(p)
}

// relayLines returns the captured "proxy stream" lines, which carry the
// error the relay saw when a stream ended early.
func (l *relayLog) relayLines() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	var out []string
	for _, line := range strings.Split(l.buf.String(), "\n") {
		if strings.Contains(line, "proxy stream") {
			out = append(out, line)
		}
	}
	if len(out) == 0 {
		return "(no relay log line)"
	}
	return strings.Join(out, "; ")
}

func TestProxy_ShutdownLeavesPostStreamRunning(t *testing.T) {
	// Capture the relay's log so a failure says how the stream ended. A
	// shutdown cut can only come through context cancellation and logs
	// "context canceled" (as the GET test's cut does); any other error is
	// a transport-level drop that BeginShutdown did not cause.
	captured := &relayLog{}
	prevLog := log.Writer()
	log.SetOutput(io.MultiWriter(prevLog, captured))
	t.Cleanup(func() { log.SetOutput(prevLog) })

	release := make(chan struct{})
	service, base, path := newSSEProxy(t, release)

	resp, err := http.Post(base+path, "application/json", strings.NewReader(`{}`))
	require.NoError(t, err)
	defer resp.Body.Close()
	reader := bufio.NewReader(resp.Body)
	line, err := reader.ReadString('\n')
	require.NoError(t, err)
	require.Equal(t, "event: first\n", line)

	rest := readRest(reader)
	service.BeginShutdown()
	select {
	case got := <-rest:
		t.Fatalf("proxied POST stream ended after BeginShutdown (read %q); relay saw: %s", got, captured.relayLines())
	case <-time.After(300 * time.Millisecond):
	}

	close(release)
	select {
	case got := <-rest:
		require.Contains(t, got, "event: last", "the tool call's final event must still be relayed")
	case <-time.After(2 * time.Second):
		t.Fatal("proxied POST stream did not finish after the agent completed")
	}
}

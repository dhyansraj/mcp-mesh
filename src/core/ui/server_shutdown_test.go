package ui

import (
	"bufio"
	"io"
	"net"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/httpserver"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry"
)

func freeAddr(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	addr := ln.Addr().String()
	require.NoError(t, ln.Close())
	return addr
}

// newShutdownTestServer builds a UI server with just enough wiring to serve
// the dashboard SSE stream through the real Run/Stop lifecycle.
func newShutdownTestServer(t *testing.T) *Server {
	t.Helper()
	db, err := database.InitializeEnt(&database.Config{
		DatabaseURL:        ":memory:",
		MaxOpenConnections: 1,
		MaxIdleConnections: 1,
	}, false)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })

	svc := registry.NewEntService(db, nil, logger.New(&config.Config{LogLevel: "ERROR"}))
	hub := NewEventHub()

	gin.SetMode(gin.TestMode)
	s := &Server{
		engine:      gin.New(),
		config:      &UIConfig{},
		httpClient:  &http.Client{},
		entService:  svc,
		eventHub:    hub,
		eventPoller: NewEventPoller(svc, hub, time.Hour),
		streamsDone: make(chan struct{}),
	}
	s.engine.GET("/api/events", s.StreamDashboardEvents)
	s.engine.GET("/ping", func(c *gin.Context) { c.Status(http.StatusNoContent) })
	return s
}

// TestServer_StopShutsListenerAndEndsStreams pins issue #1605: Stop used to
// stop only the pollers and leave the listener serving until process exit.
// It must now close the listener, end an attached dashboard SSE stream
// promptly (not at the shutdown deadline), and make Run return nil.
func TestServer_StopShutsListenerAndEndsStreams(t *testing.T) {
	s := newShutdownTestServer(t)
	addr := freeAddr(t)

	runErr := make(chan error, 1)
	go func() { runErr <- s.Run(addr) }()

	base := "http://" + addr
	require.Eventually(t, func() bool {
		resp, err := http.Get(base + "/ping")
		if err != nil {
			return false
		}
		resp.Body.Close()
		return resp.StatusCode == http.StatusNoContent
	}, 5*time.Second, 20*time.Millisecond, "UI server never came up")

	// The listener carries the shared connection limits.
	s.httpMu.Lock()
	srv := s.httpServer
	s.httpMu.Unlock()
	require.NotNil(t, srv)
	require.Equal(t, httpserver.ReadHeaderTimeout, srv.ReadHeaderTimeout)
	require.Equal(t, httpserver.IdleTimeout, srv.IdleTimeout)
	require.Equal(t, httpserver.MaxHeaderBytes, srv.MaxHeaderBytes)

	// Attach a dashboard SSE stream and wait for its first event.
	stream, err := http.Get(base + "/api/events")
	require.NoError(t, err)
	defer stream.Body.Close()
	reader := bufio.NewReader(stream.Body)
	line, err := reader.ReadString('\n')
	require.NoError(t, err)
	require.True(t, strings.HasPrefix(line, "event: connected"), "first SSE line = %q", line)

	start := time.Now()
	require.NoError(t, s.Stop())
	elapsed := time.Since(start)
	require.Less(t, elapsed, 4*time.Second,
		"Stop took %s: the SSE stream held shutdown open toward its %s deadline", elapsed, shutdownHTTPTimeout)

	// The stream ended cleanly rather than being left open.
	done := make(chan error, 1)
	go func() {
		_, err := io.Copy(io.Discard, reader)
		done <- err
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("SSE stream still open after Stop")
	}

	select {
	case err := <-runErr:
		require.NoError(t, err, "Run should return nil after a graceful Stop")
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return after Stop")
	}

	// The listener is gone.
	_, err = net.DialTimeout("tcp", addr, time.Second)
	require.Error(t, err, "listener still accepting connections after Stop")
}

// TestServer_StopBeforeRunDoesNotListen closes the race where a signal lands
// before Run registers its listener.
func TestServer_StopBeforeRunDoesNotListen(t *testing.T) {
	s := newShutdownTestServer(t)
	require.NoError(t, s.Stop())

	addr := freeAddr(t)
	require.NoError(t, s.Run(addr))
	_, err := net.DialTimeout("tcp", addr, 200*time.Millisecond)
	require.Error(t, err, "Run started listening after Stop")

	// Nothing in the background was started either: Stop has already
	// spent its cleanup, so a poller started now would leak and run on
	// against a database main is about to close.
	s.eventPoller.mu.RLock()
	running := s.eventPoller.running
	s.eventPoller.mu.RUnlock()
	require.False(t, running, "Run started the event poller after Stop")
}

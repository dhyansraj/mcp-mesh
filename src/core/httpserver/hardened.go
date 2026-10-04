// Package httpserver holds the connection limits shared by every HTTP
// listener the mesh's Go services start — the registry (main and admin
// listeners) and meshui. Keeping them in one place is the point: the
// values cannot drift between the two binaries (issues #1583, #1605).
package httpserver

import (
	"net/http"
	"time"
)

// The two deadlines that are NOT set here are deliberate. `ReadTimeout`
// and `WriteTimeout` are absolute deadlines measured from the moment
// the connection is accepted / the header is read, and both services
// serve request shapes that legitimately outlive any value we could pick:
//
//   - the registry's `GET /jobs/{id}/events?wait=` long-polls for up to
//     60s, and consumers re-poll continuously;
//   - the registry's `POST|GET /proxy/*` relays SSE responses from
//     agents for the life of the stream;
//   - meshui's `/api/events` and `/api/traces/live` are SSE streams
//     that stay open while a dashboard tab is.
//
// A `WriteTimeout` would sever all of these mid-stream, and a
// `ReadTimeout` would cap slow-but-legitimate uploads over a lossy link.
// The phases with no legitimate long case — receiving the request header,
// and sitting idle between keep-alive requests — are bounded instead,
// which is what actually stops slowloris-style connection parking.
const (
	// ReadHeaderTimeout bounds the header phase only. Every mesh client
	// and browser sends its headers in one flight, so even a badly
	// congested link is orders of magnitude inside 10s; anything slower
	// is not a client we want holding a goroutine.
	ReadHeaderTimeout = 10 * time.Second

	// IdleTimeout bounds a keep-alive connection between requests. It
	// has to sit above the agent heartbeat interval
	// (`HEALTH_CHECK_INTERVAL`, 10s by default) or every agent would
	// pay a fresh TCP+TLS handshake per heartbeat; 120s leaves ~10x
	// headroom for a slow heartbeat cadence while still reaping sockets
	// from clients that vanished without a FIN.
	IdleTimeout = 120 * time.Second

	// MaxHeaderBytes caps the request header. Go's default is 1MB, which
	// is far past anything the mesh sends: the largest real header set is
	// a bearer token plus the propagated trace/mesh headers
	// (`MCP_MESH_PROPAGATE_HEADERS`), a few KB at the top end; a browser
	// with cookies is in the same range. 64KB is still 8x nginx's total
	// header budget (large_client_header_buffers 4 8k) so no realistic
	// client trips it, while bounding per-connection memory 16x tighter
	// than Go's default.
	MaxHeaderBytes = 64 << 10
)

// NewHardened builds an http.Server carrying the connection limits above.
// Every listener goes through here so a new one cannot silently inherit
// Go's zero-valued timeouts.
//
// For a gin engine, handler must be `engine.Handler()` rather than the
// engine itself: that is what `gin.Engine.Run` passes to
// `http.ListenAndServe`, and it is where the h2c wrapper is applied when
// `UseH2C` is set.
func NewHardened(addr string, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: ReadHeaderTimeout,
		IdleTimeout:       IdleTimeout,
		MaxHeaderBytes:    MaxHeaderBytes,
	}
}

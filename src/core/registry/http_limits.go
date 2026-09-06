package registry

import (
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/registry/generated"
)

// Connection limits applied to every HTTP listener the registry starts —
// the TLS listener, the plaintext listener and the admin listener (issue
// #1583). Before this, all three were built by ``gin.Engine.Run`` /
// ``http.Server{}`` with zero-valued timeouts, so a client that opened a
// socket and dribbled headers held a goroutine and a file descriptor for
// as long as it liked.
//
// The two deadlines that are NOT set here are deliberate. ``ReadTimeout``
// and ``WriteTimeout`` are absolute deadlines measured from the moment
// the connection is accepted / the header is read, and the registry
// serves two request shapes that legitimately outlive any value we could
// pick:
//
//   - ``GET /jobs/{id}/events?wait=`` long-polls for up to 60s
//     (``listJobEventsMaxWait``), and consumers re-poll continuously.
//   - ``POST|GET /proxy/*`` relays SSE responses from agents
//     (``isEventStream`` / the flushing copy loop in ent_handlers.go),
//     which stay open for the life of the stream — unbounded by design.
//
// A ``WriteTimeout`` would sever both mid-stream, and a ``ReadTimeout``
// would cap slow-but-legitimate uploads over a lossy link. The phases
// with no legitimate long case — receiving the request header, and
// sitting idle between keep-alive requests — are bounded instead, which
// is what actually stops slowloris-style connection parking.
const (
	// defaultReadHeaderTimeout bounds the header phase only. Every mesh
	// client sends its headers in one flight, so even a badly congested
	// link is orders of magnitude inside 10s; anything slower is not a
	// client we want holding a goroutine.
	defaultReadHeaderTimeout = 10 * time.Second

	// defaultIdleTimeout bounds a keep-alive connection between
	// requests. It has to sit above the heartbeat interval
	// (``HEALTH_CHECK_INTERVAL``, 10s by default, and agents heartbeat
	// on a similar cadence) or every agent would pay a fresh TCP+TLS
	// handshake per heartbeat; 120s leaves ~10x headroom for a slow
	// heartbeat cadence while still reaping sockets from agents that
	// vanished without a FIN.
	defaultIdleTimeout = 120 * time.Second

	// defaultMaxHeaderBytes caps the request header. Go's default is
	// 1MB, which is far past anything the mesh sends: the largest real
	// header set is a bearer token plus the propagated trace/mesh
	// headers (``MCP_MESH_PROPAGATE_HEADERS``), a few KB at the top
	// end. 64KB is still 8x nginx's total header budget
	// (large_client_header_buffers 4 8k) so no realistic client trips
	// it, while bounding per-connection memory 16x tighter than Go's
	// default.
	defaultMaxHeaderBytes = 64 << 10
)

// defaultMaxRequestBodyBytes caps a single request body.
//
// The largest legitimate payload is a heartbeat: a full
// ``MeshAgentRegistration`` carrying, per tool, a description, version,
// tags, dependencies, kwargs, schema warnings and FOUR schema blobs —
// ``inputSchema`` and ``inputSchemaCanonical``, ``outputSchema`` and
// ``outputSchemaCanonical`` (see MeshToolRegistration in generated/).
// Marshalling that full shape for a tool with a 20-parameter input and a
// 10-parameter output schema measures ~9.8KB per tool: 100 tools ≈ 1MB,
// 1000 tools ≈ 9.8MB.
//
// 10MB therefore admits roughly a thousand fully-schema'd tools on one
// agent — an order of magnitude past any real agent — while capping what
// a single POST can make the registry buffer. Raise it with
// ``MCP_MESH_MAX_REQUEST_BODY_BYTES``; set that to 0 to disable the cap.
const defaultMaxRequestBodyBytes int64 = 10 << 20

// maxRequestBodyBytesFromEnv reads the ``MCP_MESH_MAX_REQUEST_BODY_BYTES``
// override. A value of 0 disables the cap; a malformed or negative value
// falls back to the default rather than leaving the registry uncapped by
// accident.
func maxRequestBodyBytesFromEnv() int64 {
	raw := os.Getenv("MCP_MESH_MAX_REQUEST_BODY_BYTES")
	if raw == "" {
		return defaultMaxRequestBodyBytes
	}
	n, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || n < 0 {
		log.Printf("[registry] invalid MCP_MESH_MAX_REQUEST_BODY_BYTES=%q, using default %d bytes", raw, defaultMaxRequestBodyBytes)
		return defaultMaxRequestBodyBytes
	}
	if n == 0 {
		log.Printf("[registry] MCP_MESH_MAX_REQUEST_BODY_BYTES=0: request body size limit disabled")
	}
	return n
}

// MaxRequestBodyMiddleware caps request bodies at limit bytes.
//
// Two layers, because clients can lie about or omit Content-Length:
// an advertised length over the limit is rejected before a single byte
// is read, and the body itself is wrapped in ``http.MaxBytesReader`` so
// a chunked or under-declared upload fails at the limit instead of
// buffering forever.
//
// The status the caller sees depends on which layer trips and on the
// handler:
//
//   - Declared Content-Length over the limit: 413, always, before the
//     handler runs and before anything is forwarded anywhere.
//   - Undeclared/chunked body over the limit on a JSON handler: the
//     decoder returns ``*http.MaxBytesError`` and writeBindError turns
//     it into 413.
//   - Undeclared/chunked body over the limit on ``/proxy/*``: the body
//     is streamed straight into the outbound request
//     (ent_handlers.go, proxyRequest), so the reader trips inside
//     ``client.Do`` and the caller gets 502, not 413 — and the first
//     ``limit`` bytes have already reached the downstream agent, which
//     sees a truncated MCP request. Declared-length proxy requests (what
//     every SDK and curl sends) are caught by the pre-check above and
//     never reach the agent at all.
//
// A limit <= 0 disables the middleware entirely.
func MaxRequestBodyMiddleware(limit int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if limit <= 0 {
			c.Next()
			return
		}
		if c.Request.ContentLength > limit {
			writeBodyTooLarge(c, limit)
			c.Abort()
			return
		}
		if c.Request.Body != nil {
			c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, limit)
		}
		c.Next()
	}
}

// writeBodyTooLarge writes the 413 used by both the Content-Length
// pre-check and the streamed-overflow path, so an operator sees the same
// message and the same knob either way.
func writeBodyTooLarge(c *gin.Context, limit int64) {
	c.JSON(http.StatusRequestEntityTooLarge, generated.ErrorResponse{
		Error:     fmt.Sprintf("Request body exceeds the %d byte limit (raise MCP_MESH_MAX_REQUEST_BODY_BYTES)", limit),
		Timestamp: time.Now().UTC(),
	})
}

// writeBindError writes the error response for a failed
// ``ShouldBindJSON``. A body that overran MaxRequestBodyMiddleware
// surfaces as ``*http.MaxBytesError`` from the decoder, and gets a 413;
// everything else keeps the historical 400 with the byte-identical
// "Invalid JSON payload" message clients already parse.
func writeBindError(c *gin.Context, err error) {
	var tooLarge *http.MaxBytesError
	if errors.As(err, &tooLarge) {
		writeBodyTooLarge(c, tooLarge.Limit)
		return
	}
	c.JSON(http.StatusBadRequest, generated.ErrorResponse{
		Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
		Timestamp: time.Now().UTC(),
	})
}

// newHardenedServer builds an http.Server carrying the connection limits
// above. Every listener the registry starts goes through here so a new
// one cannot silently inherit gin's zero-valued timeouts.
//
// handler must be ``engine.Handler()`` rather than the engine itself:
// that is what ``gin.Engine.Run`` passes to ``http.ListenAndServe``, and
// it is where the h2c wrapper is applied when ``UseH2C`` is set.
func newHardenedServer(addr string, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: defaultReadHeaderTimeout,
		IdleTimeout:       defaultIdleTimeout,
		MaxHeaderBytes:    defaultMaxHeaderBytes,
	}
}

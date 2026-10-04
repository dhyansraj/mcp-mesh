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

// Connection limits (ReadHeaderTimeout, IdleTimeout, MaxHeaderBytes) for
// every listener the registry starts live in src/core/httpserver, shared
// with meshui so the two cannot drift (issues #1583, #1605). This file
// keeps the registry-only request-body cap.

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
// The caller sees 413 in every case, and nothing is forwarded anywhere:
//
//   - Declared Content-Length over the limit: refused before the handler
//     runs.
//   - Undeclared/chunked body over the limit on a JSON handler: the
//     decoder returns ``*http.MaxBytesError`` and writeBindError turns
//     it into 413.
//   - Undeclared/chunked body on ``/proxy/*``: proxyRequestBody buffers
//     it up to the limit before forwarding, and refuses an overrun
//     before the agent sees a byte (issue #1608). At most
//     proxyBufferConcurrency (16) such bodies are buffered at once;
//     further ones wait for a slot, up to their X-Mesh-Timeout budget,
//     then get 503.
//     A declared-length proxy body is already bounded by the pre-check,
//     so it keeps streaming to the agent.
//
// A limit <= 0 disables the middleware entirely, and proxy bodies then
// stream unbounded.
func MaxRequestBodyMiddleware(limit int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if limit <= 0 {
			c.Next()
			return
		}
		c.Set(requestBodyLimitKey, limit)
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

// requestBodyLimitKey is the gin context key MaxRequestBodyMiddleware
// stores its limit under, for handlers that must enforce it themselves
// before acting on the body (proxyRequestBody).
const requestBodyLimitKey = "mcp_mesh.max_request_body_bytes"

// requestBodyLimit returns the body cap in force for this request, or 0
// when the cap is disabled or the middleware is not installed.
func requestBodyLimit(c *gin.Context) int64 {
	if v, ok := c.Get(requestBodyLimitKey); ok {
		if n, ok := v.(int64); ok {
			return n
		}
	}
	return 0
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

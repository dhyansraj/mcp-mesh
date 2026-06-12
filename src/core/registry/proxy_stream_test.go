package registry

// Tests for relayProxyStream's timeout terminal signal (#1201): when the
// X-Mesh-Timeout budget cuts an SSE exchange mid-stream, the proxy appends a
// `: mesh-proxy-timeout` SSE comment frame (spec-compliant — conforming
// clients ignore ":"-prefixed lines) so mesh clients can distinguish budget
// expiry from a normal end-of-stream. Non-SSE bodies are never decorated
// (it would corrupt the JSON payload), and the #1177 flush-per-chunk relay
// behavior is preserved.

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"strings"
	"testing"
	"time"
)

// flushRecorder implements streamFlusher over a buffer and counts flushes.
type flushRecorder struct {
	buf       bytes.Buffer
	flushes   int
	failWrite bool // when true, all writes fail (models a departed client)
}

func (f *flushRecorder) Write(p []byte) (int, error) {
	if f.failWrite {
		return 0, errors.New("client went away")
	}
	return f.buf.Write(p)
}

func (f *flushRecorder) Flush() { f.flushes++ }

// scriptedReader yields each chunk on its own Read call, then returns the
// final error (io.EOF for a clean stream end, a timeout error for a cut).
type scriptedReader struct {
	chunks []string
	final  error
}

func (r *scriptedReader) Read(p []byte) (int, error) {
	if len(r.chunks) == 0 {
		return 0, r.final
	}
	n := copy(p, r.chunks[0])
	if n < len(r.chunks[0]) {
		r.chunks[0] = r.chunks[0][n:]
	} else {
		r.chunks = r.chunks[1:]
	}
	return n, nil
}

func TestRelayProxyStream_TimeoutCutSSEAppendsMarker(t *testing.T) {
	upstream := &scriptedReader{
		chunks: []string{": ping - 2026-06-09 12:00:00+00:00\r\n\r\n"},
		final:  context.DeadlineExceeded,
	}
	w := &flushRecorder{}

	relayProxyStream(w, upstream, true, "http://agent:8080/mcp", 30*time.Second, time.Now())

	out := w.buf.String()
	if !strings.HasPrefix(out, ": ping") {
		t.Errorf("relayed bytes must precede the marker:\n%q", out)
	}
	if !strings.Contains(out, ": "+proxyTimeoutCommentMarker+" budget=30s") {
		t.Errorf("expected terminal timeout comment frame in output:\n%q", out)
	}
	if !strings.HasSuffix(out, "\n\n") {
		t.Errorf("terminal comment frame must end with a blank line:\n%q", out)
	}
	if w.flushes < 2 {
		t.Errorf("expected flush after relay chunk AND after marker, got %d flushes", w.flushes)
	}
}

func TestRelayProxyStream_SubSecondBudgetRendersFraction(t *testing.T) {
	// Sub-second budgets (e.g. MCP_MESH_PROXY_TIMEOUT=500ms) must render as a
	// fraction, not collapse to the nonsensical "budget=0s".
	upstream := &scriptedReader{
		chunks: []string{": ping\n\n"},
		final:  context.DeadlineExceeded,
	}
	w := &flushRecorder{}

	relayProxyStream(w, upstream, true, "http://agent:8080/mcp", 500*time.Millisecond, time.Now())

	out := w.buf.String()
	if !strings.Contains(out, ": "+proxyTimeoutCommentMarker+" budget=0.5s") {
		t.Errorf("sub-second budget not rendered as a fraction:\n%q", out)
	}
}

func TestRelayProxyStream_TimeoutCutNonSSENoMarker(t *testing.T) {
	// A JSON body cut by the timeout must NOT be decorated — appending
	// anything would corrupt the payload; truncation is parse-detectable.
	upstream := &scriptedReader{
		chunks: []string{`{"jsonrpc":"2.0","id":1,"result":{"par`},
		final:  os.ErrDeadlineExceeded, // net.Error with Timeout() == true
	}
	w := &flushRecorder{}

	relayProxyStream(w, upstream, false, "http://agent:8080/mcp", 30*time.Second, time.Now())

	out := w.buf.String()
	if strings.Contains(out, proxyTimeoutCommentMarker) {
		t.Errorf("non-SSE body must not get the marker appended:\n%q", out)
	}
	if out != `{"jsonrpc":"2.0","id":1,"result":{"par` {
		t.Errorf("relayed bytes altered:\n%q", out)
	}
}

func TestRelayProxyStream_CleanEOFRelaysVerbatim(t *testing.T) {
	body := "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":\"ok\"}\n\n"
	upstream := &scriptedReader{
		chunks: []string{body[:20], body[20:]},
		final:  io.EOF,
	}
	w := &flushRecorder{}

	relayProxyStream(w, upstream, true, "http://agent:8080/mcp", 30*time.Second, time.Now())

	if got := w.buf.String(); got != body {
		t.Errorf("clean stream altered:\ngot  %q\nwant %q", got, body)
	}
	if strings.Contains(w.buf.String(), proxyTimeoutCommentMarker) {
		t.Errorf("marker must not appear on a clean EOF")
	}
	// #1177 behavior: flush after every chunk.
	if w.flushes != 2 {
		t.Errorf("expected one flush per chunk (2), got %d", w.flushes)
	}
}

func TestRelayProxyStream_NonTimeoutErrorNoMarker(t *testing.T) {
	upstream := &scriptedReader{
		chunks: []string{": ping\n\n"},
		final:  errors.New("connection reset by peer"),
	}
	w := &flushRecorder{}

	relayProxyStream(w, upstream, true, "http://agent:8080/mcp", 30*time.Second, time.Now())

	if strings.Contains(w.buf.String(), proxyTimeoutCommentMarker) {
		t.Errorf("non-timeout upstream error must not emit the timeout marker:\n%q", w.buf.String())
	}
}

func TestRelayProxyStream_ClientGoneStopsRelay(t *testing.T) {
	upstream := &scriptedReader{
		chunks: []string{"data: chunk1\n\n", "data: chunk2\n\n"},
		final:  io.EOF,
	}
	w := &flushRecorder{failWrite: true}

	// Must return without panicking or spinning; nothing relayed, no flushes.
	relayProxyStream(w, upstream, true, "http://agent:8080/mcp", 30*time.Second, time.Now())

	if w.buf.Len() != 0 || w.flushes != 0 {
		t.Errorf("expected no output/flushes after client write failure, got %q / %d flushes", w.buf.String(), w.flushes)
	}
}

// TestIsSSEContentType pins the proxy's SSE detection to exact media-type
// matching: parameterized and case-variant forms of text/event-stream are
// SSE, while unrelated types that merely embed the string (which a substring
// check would false-positive on) are not.
func TestIsSSEContentType(t *testing.T) {
	cases := []struct {
		contentType string
		want        bool
	}{
		{"text/event-stream", true},
		{"text/event-stream; charset=utf-8", true},
		{"TEXT/EVENT-STREAM", true},
		{"application/json", false},
		{"application/json; charset=utf-8", false},
		{"text/event-stream-json", false},
		{`application/json; note="text/event-stream"`, false},
		{"", false},
		{"not a media type;;;", false},
	}
	for _, c := range cases {
		t.Run(c.contentType, func(t *testing.T) {
			if got := isSSEContentType(c.contentType); got != c.want {
				t.Errorf("isSSEContentType(%q) = %v, want %v", c.contentType, got, c.want)
			}
		})
	}
}

func TestIsProxyTimeoutError(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"context deadline", context.DeadlineExceeded, true},
		{"wrapped context deadline", errors.Join(errors.New("while reading body"), context.DeadlineExceeded), true},
		{"net timeout (os deadline)", os.ErrDeadlineExceeded, true},
		{"plain error", errors.New("connection reset"), false},
		{"eof", io.EOF, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := isProxyTimeoutError(c.err); got != c.want {
				t.Errorf("isProxyTimeoutError(%v) = %v, want %v", c.err, got, c.want)
			}
		})
	}
}

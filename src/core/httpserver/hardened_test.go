package httpserver

import (
	"net/http"
	"testing"
)

func TestNewHardened_SetsConnectionLimits(t *testing.T) {
	srv := NewHardened(":8000", http.NotFoundHandler())

	if srv.Addr != ":8000" {
		t.Errorf("Addr = %q, want :8000", srv.Addr)
	}
	if srv.ReadHeaderTimeout != ReadHeaderTimeout {
		t.Errorf("ReadHeaderTimeout = %v, want %v", srv.ReadHeaderTimeout, ReadHeaderTimeout)
	}
	if srv.IdleTimeout != IdleTimeout {
		t.Errorf("IdleTimeout = %v, want %v", srv.IdleTimeout, IdleTimeout)
	}
	if srv.MaxHeaderBytes != MaxHeaderBytes {
		t.Errorf("MaxHeaderBytes = %d, want %d", srv.MaxHeaderBytes, MaxHeaderBytes)
	}
	// Absolute deadlines would sever long-polls and SSE streams.
	if srv.ReadTimeout != 0 || srv.WriteTimeout != 0 {
		t.Errorf("ReadTimeout/WriteTimeout = %v/%v, want both unset", srv.ReadTimeout, srv.WriteTimeout)
	}
}

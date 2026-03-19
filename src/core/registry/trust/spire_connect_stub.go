//go:build !spire

package trust

import (
	"context"
	"fmt"
)

// NewSPIRE is a stub that returns an error when built without the spire tag.
// Build with `go build -tags spire` to enable SPIRE Workload API support.
func NewSPIRE(_ context.Context, socketPath string) (*SPIREBackend, error) {
	return nil, fmt.Errorf("SPIRE backend requires build with -tags spire (socket: %s)", socketPath)
}

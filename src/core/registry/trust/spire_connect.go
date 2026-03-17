//go:build spire

package trust

import (
	"context"
	"crypto/x509"
	"fmt"
	"time"

	"github.com/spiffe/go-spiffe/v2/workloadapi"
)

// NewSPIRE creates a SPIREBackend by fetching trust bundles from the
// SPIRE agent Workload API via Unix domain socket.
//
// The socket path should be the SPIRE agent's Workload API socket,
// typically /run/spire/agent/sockets/agent.sock (mounted into pods
// via hostPath or CSI driver in K8s).
func NewSPIRE(ctx context.Context, socketPath string) (*SPIREBackend, error) {
	addr := "unix://" + socketPath

	connCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	client, err := workloadapi.New(connCtx, workloadapi.WithAddr(addr))
	if err != nil {
		return nil, fmt.Errorf("connecting to SPIRE agent at %s: %w", socketPath, err)
	}
	defer client.Close()

	fetchCtx, fetchCancel := context.WithTimeout(ctx, 10*time.Second)
	defer fetchCancel()

	x509Ctx, err := client.FetchX509Context(fetchCtx)
	if err != nil {
		return nil, fmt.Errorf("fetching X.509 context from SPIRE agent: %w", err)
	}

	// Convert X509BundleSet to map[string][]*x509.Certificate
	bundles := make(map[string][]*x509.Certificate)
	for _, b := range x509Ctx.Bundles.Bundles() {
		domain := b.TrustDomain().String()
		bundles[domain] = b.X509Authorities()
	}

	if len(bundles) == 0 {
		return nil, fmt.Errorf("no trust bundles received from SPIRE agent at %s", socketPath)
	}

	return NewSPIREFromBundles(bundles), nil
}

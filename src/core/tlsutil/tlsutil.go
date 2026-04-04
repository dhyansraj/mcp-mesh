package tlsutil

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
)

// LoadFromEnv loads TLS configuration from environment variables with the given prefix.
// For prefix "REDIS_TLS", it reads:
//   - REDIS_TLS_CA          — path to CA certificate file
//   - REDIS_TLS_CERT        — path to client certificate file
//   - REDIS_TLS_KEY         — path to client key file
//   - REDIS_TLS_SKIP_VERIFY — "true" to skip server certificate verification
//
// Returns nil, nil if no TLS environment variables are set (caller should use defaults).
func LoadFromEnv(prefix string) (*tls.Config, error) {
	caPath := os.Getenv(prefix + "_CA")
	certPath := os.Getenv(prefix + "_CERT")
	keyPath := os.Getenv(prefix + "_KEY")
	skipVerify := strings.ToLower(os.Getenv(prefix+"_SKIP_VERIFY")) == "true"

	if caPath == "" && certPath == "" && keyPath == "" && !skipVerify {
		return nil, nil
	}

	tlsConfig := &tls.Config{}

	if caPath != "" {
		caCert, err := os.ReadFile(caPath)
		if err != nil {
			return nil, fmt.Errorf("failed to read CA certificate from %s: %w", caPath, err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(caCert) {
			return nil, fmt.Errorf("failed to parse CA certificate from %s", caPath)
		}
		tlsConfig.RootCAs = pool
	}

	if certPath != "" && keyPath != "" {
		cert, err := tls.LoadX509KeyPair(certPath, keyPath)
		if err != nil {
			return nil, fmt.Errorf("failed to load client certificate: %w", err)
		}
		tlsConfig.Certificates = []tls.Certificate{cert}
	} else if certPath != "" || keyPath != "" {
		return nil, fmt.Errorf("both %s_CERT and %s_KEY must be set together", prefix, prefix)
	}

	if skipVerify {
		tlsConfig.InsecureSkipVerify = true
	}

	return tlsConfig, nil
}

// NewHTTPTransport creates an *http.Transport with the given TLS config applied.
// If tlsConfig is nil, returns a transport with default TLS settings.
func NewHTTPTransport(tlsConfig *tls.Config) *http.Transport {
	return &http.Transport{
		TLSClientConfig:     tlsConfig,
		MaxIdleConns:        20,
		MaxIdleConnsPerHost: 10,
		IdleConnTimeout:     90 * time.Second,
	}
}

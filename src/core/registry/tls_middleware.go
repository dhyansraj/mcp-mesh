package registry

import (
	"fmt"
	"log"
	"log/slog"
	"strings"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/registry/trust"
)

// Accepted values of MCP_MESH_TLS_MODE.
const (
	TLSModeOff    = "off"
	TLSModeAuto   = "auto"
	TLSModeStrict = "strict"
)

// NormalizeTLSMode validates and canonicalizes an MCP_MESH_TLS_MODE value
// (issue #1626). Surrounding whitespace and case are ignored, and an empty
// value means "off" (the documented default). Anything else is an error
// that names the variable and the accepted values: an unrecognized mode
// used to fall through to "auto", so a misspelled "stirct" or a "STRICT"
// silently admitted certless clients — the opposite of what was asked.
//
// NewServer normalizes RegistryConfig.TlsMode once with this, so every
// consumer (TLSVerifyMiddleware, the listener and trust-chain gates,
// tlsEnabled, the admin listener) reads the canonical value.
func NormalizeTLSMode(raw string) (string, error) {
	mode := strings.ToLower(strings.TrimSpace(raw))
	switch mode {
	case "":
		return TLSModeOff, nil
	case TLSModeOff, TLSModeAuto, TLSModeStrict:
		return mode, nil
	}
	return "", fmt.Errorf("invalid MCP_MESH_TLS_MODE=%q: accepted values are %s, %s, %s",
		raw, TLSModeOff, TLSModeAuto, TLSModeStrict)
}

// tlsModeRequested reports whether a normalized mode asks for TLS.
func tlsModeRequested(mode string) bool {
	return mode != "" && mode != TLSModeOff
}

// TLSVerifyMiddleware creates a Gin middleware that extracts and validates
// client TLS certificates using the provided TrustChain.
//
// Modes:
//   - "off": skip validation entirely (backward compatible)
//   - "auto": validate if cert is present, allow without cert
//   - "strict": require a valid client certificate, reject with 403 otherwise
//
// mode is expected to be normalized (NormalizeTLSMode). Any value that is
// not "off" or "auto" is enforced as "strict", so a caller that skips
// normalization fails closed rather than open.
func TLSVerifyMiddleware(chain *trust.TrustChain, mode string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if mode == TLSModeOff {
			c.Next()
			return
		}

		// Extract peer certs from TLS connection
		if c.Request.TLS == nil || len(c.Request.TLS.PeerCertificates) == 0 {
			if mode != TLSModeAuto {
				c.AbortWithStatusJSON(403, gin.H{"error": "client certificate required"})
				return
			}
			c.Next()
			return
		}

		result, err := chain.Verify(c.Request.TLS.PeerCertificates)
		if err != nil {
			log.Printf("[trust] certificate verification failed: %v (from %s)", err, c.Request.RemoteAddr)
			// Both auto and strict reject a certificate that fails
			// verification; auto only differs in admitting a missing one
			// (handled above).
			c.AbortWithStatusJSON(403, gin.H{"error": "untrusted certificate", "detail": err.Error()})
			return
		}

		if c.Request.Method == "POST" {
			slog.Debug("agent registration verified", "entity_id", result.EntityID, "cert_subject", result.CertSubject)
		}

		c.Set("entity_id", result.EntityID)
		c.Set("cert_subject", result.CertSubject)
		c.Next()
	}
}

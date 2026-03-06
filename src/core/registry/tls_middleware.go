package registry

import (
	"log"
	"log/slog"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/registry/trust"
)

// TLSVerifyMiddleware creates a Gin middleware that extracts and validates
// client TLS certificates using the provided TrustChain.
//
// Modes:
//   - "off": skip validation entirely (backward compatible)
//   - "auto": validate if cert is present, allow without cert
//   - "strict": require a valid client certificate, reject with 403 otherwise
func TLSVerifyMiddleware(chain *trust.TrustChain, mode string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if mode == "off" {
			c.Next()
			return
		}

		// Extract peer certs from TLS connection
		if c.Request.TLS == nil || len(c.Request.TLS.PeerCertificates) == 0 {
			if mode == "strict" {
				c.AbortWithStatusJSON(403, gin.H{"error": "client certificate required"})
				return
			}
			c.Next()
			return
		}

		result, err := chain.Verify(c.Request.TLS.PeerCertificates)
		if err != nil {
			if mode == "strict" {
				log.Printf("[trust] REJECTED: %v (from %s)", err, c.Request.RemoteAddr)
				c.AbortWithStatusJSON(403, gin.H{"error": "untrusted certificate", "detail": err.Error()})
				return
			}
			c.Next()
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

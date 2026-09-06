package ui

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// maxRegistryResponseBytes caps the registry response the UI will buffer
// and forward. Every proxied endpoint is a bounded JSON document (agent
// lists, traces, job pages), so 10MB is far past any legitimate reply;
// past it the request fails with 502 rather than forwarding a body that
// was cut mid-token.
const maxRegistryResponseBytes int64 = 10 * 1024 * 1024

// proxyToRegistry forwards an API request to the registry and writes back the response.
// The /api prefix is stripped before forwarding: /api/health -> {registryURL}/health.
func (s *Server) proxyToRegistry(c *gin.Context) {
	// Strip the /api prefix to get the registry-relative path
	registryPath := strings.TrimPrefix(c.Request.URL.Path, "/api")
	if registryPath == "" {
		registryPath = "/"
	}

	targetURL := fmt.Sprintf("%s%s", s.config.RegistryURL, registryPath)

	// Forward query parameters
	if rawQuery := c.Request.URL.RawQuery; rawQuery != "" {
		targetURL += "?" + rawQuery
	}

	req, err := http.NewRequestWithContext(c.Request.Context(), c.Request.Method, targetURL, nil)
	if err != nil {
		log.Printf("proxy: failed to create request: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create proxy request"})
		return
	}

	// Forward relevant headers from the original request
	if accept := c.GetHeader("Accept"); accept != "" {
		req.Header.Set("Accept", accept)
	}
	if ct := c.GetHeader("Content-Type"); ct != "" {
		req.Header.Set("Content-Type", ct)
	}

	resp, err := s.httpClient.Do(req)
	if err != nil {
		log.Printf("proxy: registry unavailable at %s: %v", s.config.RegistryURL, err)
		c.JSON(http.StatusBadGateway, gin.H{
			"error":        "Registry unavailable",
			"registry_url": s.config.RegistryURL,
		})
		return
	}
	defer resp.Body.Close()

	// Read one byte past the cap so an over-large response is detectable.
	// It used to be a plain LimitReader at the cap, which silently handed
	// the client a truncated body — invalid JSON carrying the upstream's
	// 200 — with nothing in the response to say it had been cut (issue
	// #1583). A response this size is a registry bug or a runaway query,
	// so fail the request instead of corrupting it.
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxRegistryResponseBytes+1))
	if err != nil {
		log.Printf("proxy: failed to read registry response: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "Failed to read registry response"})
		return
	}
	if int64(len(body)) > maxRegistryResponseBytes {
		log.Printf("proxy: registry response for %s exceeded %d bytes; refusing to forward a truncated body", registryPath, maxRegistryResponseBytes)
		c.JSON(http.StatusBadGateway, gin.H{
			"error": fmt.Sprintf("Registry response exceeded the %d byte limit", maxRegistryResponseBytes),
			"path":  registryPath,
		})
		return
	}

	// Forward content-type from registry
	contentType := resp.Header.Get("Content-Type")
	if contentType == "" {
		contentType = "application/json"
	}

	c.Data(resp.StatusCode, contentType, body)
}

package ui

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

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

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("proxy: failed to read registry response: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "Failed to read registry response"})
		return
	}

	// Forward content-type from registry
	contentType := resp.Header.Get("Content-Type")
	if contentType == "" {
		contentType = "application/json"
	}

	c.Data(resp.StatusCode, contentType, body)
}

package ui

import "crypto/tls"

// UIConfig holds configuration for the MCP Mesh UI server.
type UIConfig struct {
	Port           int
	RegistryURL    string
	LogLevel       string
	TracingEnabled bool
	RedisURL       string
	TempoQueryURL  string
	RegistryTLS    *tls.Config
}

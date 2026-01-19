package registry

// Config represents server configuration
type Config struct {
	Port                     int
	Debug                    bool
	DatabaseURL              string
	CacheTTL                 int
	DefaultTimeoutThreshold  int
	DefaultEvictionThreshold int
	EnableResponseCache      bool
	HealthCheckInterval      int
	StartupCleanupThreshold  int // Threshold in seconds for marking stale agents on startup
}

// DefaultServiceConfig returns default service configuration
func DefaultServiceConfig() *RegistryConfig {
	return &RegistryConfig{
		CacheTTL:                 30,
		DefaultTimeoutThreshold:  60,
		DefaultEvictionThreshold: 120,
		StartupCleanupThreshold:  30, // Mark agents as stale if no heartbeat for 30s on startup
		EnableResponseCache:      false, // NO CACHE - Multiple registry instances
	}
}

// AgentQueryParams represents agent query parameters
type AgentQueryParams struct {
	Status              string   `form:"status"`
	Namespace           string   `form:"namespace"`
	Type                string   `form:"type"`
	Tags                string   `form:"tags"`
	Capabilities        []string `form:"capabilities"`
	FuzzyMatch          bool     `form:"fuzzy"`
	CapabilityCategory  string   `form:"capability_category"`
	CapabilityStability string   `form:"capability_stability"`
	CapabilityTags      []string `form:"capability_tags"`
}

// CapabilityQueryParams represents capability search parameters
type CapabilityQueryParams struct {
	Name        string   `form:"name"`
	Version     string   `form:"version"`
	Tags        []string `form:"tags"`
	AgentStatus string   `form:"status"`
	Namespace   string   `form:"namespace"`
	FuzzyMatch  bool     `form:"fuzzy"`
}

// RegisterAgentRequest is an alias for AgentRegistrationRequest (for compatibility)
type RegisterAgentRequest = AgentRegistrationRequest

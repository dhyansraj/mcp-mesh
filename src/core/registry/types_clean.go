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

// JobQueryParams collects the query-string filters for GET /jobs (issue
// #973). Mirrors generated.ListJobsParams but with the binding-friendly
// non-pointer + form-tag shape the handler binds with ShouldBindQuery, plus
// the comma-split status parsing handled in the handler.
//
// `Status` is the raw, comma-separated value as it arrived on the wire;
// the handler splits + validates against the JobStatus enum and rejects
// unknown values with 400 before calling the service.
type JobQueryParams struct {
	Status          string `form:"status"`
	OwnerInstanceID string `form:"owner_instance_id"`
	Capability      string `form:"capability"`
	SubmittedSince  int64  `form:"submitted_since"`
	Limit           int    `form:"limit"`
	Cursor          string `form:"cursor"`
}

// JobsListInput is the service-layer projection of JobQueryParams after
// the handler validates the comma-separated status list against the enum.
type JobsListInput struct {
	Statuses        []string
	OwnerInstanceID string
	Capability      string
	SubmittedSince  int64 // Unix epoch seconds; 0 = no filter
	Limit           int
	Cursor          string
}

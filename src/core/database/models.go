package database

import (
	"encoding/json"
	"fmt"
	"time"
)

// JSON helper functions for marshaling/unmarshaling
func marshalJSON(v interface{}) string {
	if v == nil {
		return "{}"
	}
	if bytes, err := json.Marshal(v); err == nil {
		return string(bytes)
	}
	return "{}"
}

func unmarshalJSON(data string, v interface{}) error {
	if data == "" {
		data = "{}"
	}
	return json.Unmarshal([]byte(data), v)
}

// Agent represents the agents table - matches Python SQLAlchemy schema exactly
type Agent struct {
	// Primary fields
	ID        string `json:"id"`
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
	Endpoint  string `json:"endpoint"`
	Status    string `json:"status"`

	// Kubernetes-style metadata (stored as JSON strings to match Python)
	Labels      string `json:"labels"`      // JSON string
	Annotations string `json:"annotations"` // JSON string

	// Timestamps and versioning
	CreatedAt       time.Time  `json:"created_at"`
	UpdatedAt       time.Time  `json:"updated_at"`
	ResourceVersion string     `json:"resource_version"`
	LastHeartbeat   *time.Time `json:"last_heartbeat"`

	// Health configuration (matching Python RegistryAgent model exactly)
	HealthInterval    int    `json:"health_interval"`
	TimeoutThreshold  int    `json:"timeout_threshold"`   // Seconds before marked as degraded
	EvictionThreshold int    `json:"eviction_threshold"` // Seconds before marked as expired
	AgentType         string `json:"agent_type"`         // For type-specific thresholds

	// Configuration and security (stored as JSON strings to match Python)
	Config          string  `json:"config"`           // JSON string
	SecurityContext *string `json:"security_context"`
	Dependencies    string  `json:"dependencies"` // JSON array string
}

// PrepareForInsert sets timestamps and resource version for new agents
func (a *Agent) PrepareForInsert() {
	now := time.Now().UTC()
	a.CreatedAt = now
	a.UpdatedAt = now
	if a.ResourceVersion == "" {
		a.ResourceVersion = generateResourceVersion()
	}
}

// PrepareForUpdate sets updated timestamp and new resource version
func (a *Agent) PrepareForUpdate() {
	a.UpdatedAt = time.Now().UTC()
	a.ResourceVersion = generateResourceVersion()
}

// Capability represents the capabilities table - matches Python SQLAlchemy schema exactly
type Capability struct {
	ID                   int       `json:"id"`
	AgentID              string    `json:"agent_id"`
	Name                 string    `json:"name"`
	Description          *string   `json:"description"`
	Version              string    `json:"version"`
	ParametersSchema     *string   `json:"parameters_schema"`     // JSON string
	SecurityRequirements *string   `json:"security_requirements"` // JSON array string
	CreatedAt            time.Time `json:"created_at"`
	UpdatedAt            time.Time `json:"updated_at"`
}

// AgentHealth represents the agent_health table
type AgentHealth struct {
	ID             int       `json:"id"`
	AgentID        string    `json:"agent_id"`
	Status         string    `json:"status"`
	Timestamp      time.Time `json:"timestamp"`
	Checks         string    `json:"checks"`         // JSON object string
	Errors         string    `json:"errors"`         // JSON array string
	UptimeSeconds  int       `json:"uptime_seconds"`
	Metadata       string    `json:"metadata"` // JSON string
}


// RegistryEvent represents the registry_events table
type RegistryEvent struct {
	ID              int       `json:"id"`
	EventType       string    `json:"event_type"`
	AgentID         string    `json:"agent_id"`
	Timestamp       time.Time `json:"timestamp"`
	ResourceVersion string    `json:"resource_version"`
	Data            *string   `json:"data"` // JSON string
	Source          string    `json:"source"`
	Metadata        string    `json:"metadata"` // JSON string
}


// ServiceContract represents the service_contracts table
type ServiceContract struct {
	ID                 int       `json:"id"`
	AgentID            string    `json:"agent_id"`
	ServiceName        string    `json:"service_name"`
	ServiceVersion     string    `json:"service_version"`
	Description        *string   `json:"description"`
	ContractVersion    string    `json:"contract_version"`
	CompatibilityLevel string    `json:"compatibility_level"`
	CreatedAt          time.Time `json:"created_at"`
	UpdatedAt          time.Time `json:"updated_at"`
}


// MethodMetadata represents the method_metadata table
type MethodMetadata struct {
	ID                   int       `json:"id"`
	ContractID           int       `json:"contract_id"`
	MethodName           string    `json:"method_name"`
	SignatureData        string    `json:"signature_data"` // JSON string
	ReturnType           *string   `json:"return_type"`
	IsAsync              bool      `json:"is_async"`
	MethodType           string    `json:"method_type"`
	Docstring            *string   `json:"docstring"`
	ServiceVersion       string    `json:"service_version"`
	StabilityLevel       string    `json:"stability_level"`
	DeprecationWarning   *string   `json:"deprecation_warning"`
	ExpectedComplexity   string    `json:"expected_complexity"`
	TimeoutHint          int       `json:"timeout_hint"`
	ResourceRequirements string    `json:"resource_requirements"` // JSON string
	CreatedAt            time.Time `json:"created_at"`
	UpdatedAt            time.Time `json:"updated_at"`
}


// MethodParameter represents the method_parameters table
type MethodParameter struct {
	ID            int     `json:"id"`
	MethodID      int     `json:"method_id"`
	ParameterName string  `json:"parameter_name"`
	ParameterType string  `json:"parameter_type"`
	ParameterKind string  `json:"parameter_kind"`
	DefaultValue  *string `json:"default_value"` // JSON string
	Annotation    *string `json:"annotation"`    // JSON string
	HasDefault    bool    `json:"has_default"`
	IsOptional    bool    `json:"is_optional"`
	Position      int     `json:"position"`
}


// MethodCapability represents the method_capabilities table
type MethodCapability struct {
	ID             int    `json:"id"`
	MethodID       int    `json:"method_id"`
	CapabilityName string `json:"capability_name"`
	CapabilityID   *int   `json:"capability_id"`
}


// CapabilityMethodMapping represents the capability_method_mapping table
type CapabilityMethodMapping struct {
	ID           int       `json:"id"`
	CapabilityID int       `json:"capability_id"`
	MethodID     int       `json:"method_id"`
	MappingType  string    `json:"mapping_type"`
	Priority     int       `json:"priority"`
	CreatedAt    time.Time `json:"created_at"`
}


// SchemaVersion represents the schema_version table
type SchemaVersion struct {
	Version   int       `json:"version"`
	AppliedAt time.Time `json:"applied_at"`
}


// Helper function to generate resource version (timestamp in milliseconds)
func generateResourceVersion() string {
	return fmt.Sprintf("%d", time.Now().UnixMilli())
}

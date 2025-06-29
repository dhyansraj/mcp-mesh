package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"mcp-mesh/src/core/database"
)

// Config holds all configuration for the MCP Mesh Registry
// MUST match Python configuration loading behavior exactly
type Config struct {
	// Server configuration
	Host string `env:"HOST" envDefault:"localhost"`
	Port int    `env:"PORT" envDefault:"8000"`

	// Database configuration
	Database *database.Config

	// Registry configuration
	RegistryName        string `env:"REGISTRY_NAME" envDefault:"mcp-mesh-registry"`
	HealthCheckInterval int    `env:"HEALTH_CHECK_INTERVAL" envDefault:"30"`

	// Cache configuration
	CacheTTL            int  `env:"CACHE_TTL" envDefault:"30"` // seconds
	EnableResponseCache bool `env:"ENABLE_RESPONSE_CACHE" envDefault:"true"`

	// Health monitoring configuration
	DefaultTimeoutThreshold  int `env:"DEFAULT_TIMEOUT_THRESHOLD" envDefault:"60"`   // seconds
	DefaultEvictionThreshold int `env:"DEFAULT_EVICTION_THRESHOLD" envDefault:"120"` // seconds

	// CORS configuration
	EnableCORS     bool     `env:"ENABLE_CORS" envDefault:"true"`
	AllowedOrigins []string `env:"ALLOWED_ORIGINS" envDefault:"*"`
	AllowedMethods []string `env:"ALLOWED_METHODS" envDefault:"GET,POST,PUT,DELETE,OPTIONS"`
	AllowedHeaders []string `env:"ALLOWED_HEADERS" envDefault:"*"`

	// Logging configuration
	LogLevel  string `env:"MCP_MESH_LOG_LEVEL" envDefault:"INFO"`
	DebugMode bool   `env:"MCP_MESH_DEBUG_MODE" envDefault:"false"`
	AccessLog bool   `env:"ACCESS_LOG" envDefault:"true"`

	// Feature flags
	EnableMetrics    bool `env:"ENABLE_METRICS" envDefault:"true"`
	EnablePrometheus bool `env:"ENABLE_PROMETHEUS" envDefault:"true"`
	EnableEvents     bool `env:"ENABLE_EVENTS" envDefault:"true"`
}

// LoadFromEnv loads configuration from environment variables
// MUST match Python configuration loading behavior exactly
func LoadFromEnv() *Config {
	config := &Config{
		Host:                     getEnvString("HOST", "localhost"),
		Port:                     getEnvInt("PORT", 8000),
		RegistryName:             getEnvString("REGISTRY_NAME", "mcp-mesh-registry"),
		HealthCheckInterval:      getEnvInt("HEALTH_CHECK_INTERVAL", 30),
		CacheTTL:                 getEnvInt("CACHE_TTL", 30),
		EnableResponseCache:      getEnvBool("ENABLE_RESPONSE_CACHE", true),
		DefaultTimeoutThreshold:  getEnvInt("DEFAULT_TIMEOUT_THRESHOLD", 60),
		DefaultEvictionThreshold: getEnvInt("DEFAULT_EVICTION_THRESHOLD", 120),
		EnableCORS:               getEnvBool("ENABLE_CORS", true),
		AllowedOrigins:           getEnvStringSlice("ALLOWED_ORIGINS", []string{"*"}),
		AllowedMethods:           getEnvStringSlice("ALLOWED_METHODS", []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"}),
		AllowedHeaders:           getEnvStringSlice("ALLOWED_HEADERS", []string{"*"}),
		LogLevel:                 getEnvString("MCP_MESH_LOG_LEVEL", "INFO"),
		DebugMode:                getEnvBool("MCP_MESH_DEBUG_MODE", false),
		AccessLog:                getEnvBool("ACCESS_LOG", true),
		EnableMetrics:            getEnvBool("ENABLE_METRICS", true),
		EnablePrometheus:         getEnvBool("ENABLE_PROMETHEUS", true),
		EnableEvents:             getEnvBool("ENABLE_EVENTS", true),
	}

	// Database configuration (matches Python DatabaseConfig)
	config.Database = &database.Config{
		DatabaseURL:        getEnvString("DATABASE_URL", "mcp_mesh_registry.db"),
		ConnectionTimeout:  getEnvInt("DB_CONNECTION_TIMEOUT", 30),
		BusyTimeout:        getEnvInt("DB_BUSY_TIMEOUT", 5000),
		JournalMode:        getEnvString("DB_JOURNAL_MODE", "WAL"),
		Synchronous:        getEnvString("DB_SYNCHRONOUS", "NORMAL"),
		CacheSize:          getEnvInt("DB_CACHE_SIZE", 10000),
		EnableForeignKeys:  getEnvBool("DB_ENABLE_FOREIGN_KEYS", true),
		MaxOpenConnections: getEnvInt("DB_MAX_OPEN_CONNECTIONS", 25),
		MaxIdleConnections: getEnvInt("DB_MAX_IDLE_CONNECTIONS", 5),
		ConnMaxLifetime:    getEnvInt("DB_CONN_MAX_LIFETIME", 300),
	}

	return config
}

// Validate ensures configuration is valid
func (c *Config) Validate() error {
	// Basic validation
	if c.Port < 1 || c.Port > 65535 {
		return fmt.Errorf("invalid port: %d", c.Port)
	}

	if c.HealthCheckInterval < 1 {
		return fmt.Errorf("health check interval must be positive: %d", c.HealthCheckInterval)
	}

	if c.CacheTTL < 0 {
		return fmt.Errorf("cache TTL must be non-negative: %d", c.CacheTTL)
	}

	// Validate log level (case insensitive)
	validLogLevels := map[string]bool{
		"DEBUG":    true,
		"INFO":     true,
		"WARNING":  true,
		"ERROR":    true,
		"CRITICAL": true,
	}
	upperLogLevel := strings.ToUpper(c.LogLevel)
	if !validLogLevels[upperLogLevel] {
		return fmt.Errorf("invalid log level: %s (valid: DEBUG, INFO, WARNING, ERROR, CRITICAL)", c.LogLevel)
	}

	// If debug mode is enabled, force log level to DEBUG
	if c.DebugMode {
		c.LogLevel = "DEBUG"
	}

	return nil
}

// GetDatabaseURL returns the database URL with proper formatting
func (c *Config) GetDatabaseURL() string {
	return c.Database.DatabaseURL
}

// IsProduction determines if running in production mode
func (c *Config) IsProduction() bool {
	env := strings.ToLower(getEnvString("ENVIRONMENT", "development"))
	return env == "production" || env == "prod"
}

// IsDevelopment determines if running in development mode
func (c *Config) IsDevelopment() bool {
	return !c.IsProduction()
}

// IsDebugMode determines if debug mode is enabled
func (c *Config) IsDebugMode() bool {
	return c.DebugMode || strings.ToUpper(c.LogLevel) == "DEBUG"
}

// ShouldLogAtLevel checks if messages at the given level should be logged
func (c *Config) ShouldLogAtLevel(level string) bool {
	levelPriority := map[string]int{
		"DEBUG":    0,
		"INFO":     1,
		"WARNING":  2,
		"ERROR":    3,
		"CRITICAL": 4,
	}

	currentLevel := strings.ToUpper(c.LogLevel)
	checkLevel := strings.ToUpper(level)

	currentPriority, exists := levelPriority[currentLevel]
	if !exists {
		currentPriority = 1 // Default to INFO
	}

	checkPriority, exists := levelPriority[checkLevel]
	if !exists {
		return false
	}

	return checkPriority >= currentPriority
}

// Helper functions for environment variable parsing

func getEnvString(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if intValue, err := strconv.Atoi(value); err == nil {
			return intValue
		}
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		if boolValue, err := strconv.ParseBool(value); err == nil {
			return boolValue
		}
	}
	return defaultValue
}

func getEnvStringSlice(key string, defaultValue []string) []string {
	if value := os.Getenv(key); value != "" {
		return strings.Split(value, ",")
	}
	return defaultValue
}

// GetHealthConfiguration returns health monitoring configuration
func (c *Config) GetHealthConfiguration() map[string]interface{} {
	return map[string]interface{}{
		"default_timeout_threshold":  c.DefaultTimeoutThreshold,
		"default_eviction_threshold": c.DefaultEvictionThreshold,
		"check_interval":             c.HealthCheckInterval,
		"agent_type_configs": map[string]map[string]int{
			"file-agent": {
				"timeout_threshold":  90,
				"eviction_threshold": 180,
			},
			"worker": {
				"timeout_threshold":  45,
				"eviction_threshold": 90,
			},
			"critical": {
				"timeout_threshold":  30,
				"eviction_threshold": 60,
			},
		},
	}
}

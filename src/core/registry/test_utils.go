package registry

import (
	"encoding/json"
	"io/ioutil"
	"log"
	"os"
	"path/filepath"
	"testing"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/logger"
)

// TestLogger is a simple logger for tests
type TestLogger struct{}

func (l *TestLogger) Debug(format string, args ...interface{}) {
	log.Printf("[DEBUG] "+format, args...)
}

func (l *TestLogger) Info(format string, args ...interface{}) {
	log.Printf("[INFO] "+format, args...)
}

func (l *TestLogger) Warning(format string, args ...interface{}) {
	log.Printf("[WARNING] "+format, args...)
}

func (l *TestLogger) Error(format string, args ...interface{}) {
	log.Printf("[ERROR] "+format, args...)
}

func (l *TestLogger) Printf(format string, args ...interface{}) {
	log.Printf(format, args...)
}

func (l *TestLogger) IsDebugEnabled() bool {
	return true
}

func (l *TestLogger) SetGinMode() {
	os.Setenv("GIN_MODE", "test")
}

func (l *TestLogger) LogLevel() string {
	return "INFO"
}

func (l *TestLogger) GetStartupBanner() string {
	return "Test Mode"
}

// createTestLogger creates a logger for testing
func createTestLogger(cfg interface{}) *logger.Logger {
	// Create a minimal test config
	testConfig := &config.Config{
		LogLevel:  "INFO",
		DebugMode: false,
	}
	return logger.New(testConfig)
}

// setupTestService creates a test EntService with an in-memory database
func setupTestService(t *testing.T) *EntService {
	// Use separate in-memory database for each test to ensure isolation
	config := &database.Config{
		DatabaseURL:        ":memory:",
		MaxOpenConnections: 1,
		MaxIdleConnections: 1,
	}

	entDB, err := database.InitializeEnt(config, true) // Enable debug for tests to see SQL
	if err != nil {
		t.Fatalf("Failed to initialize test database: %v", err)
	}

	// Create test logger using the actual logger package with a minimal config
	// We'll create a minimal config struct inline
	testConfig := &struct {
		LogLevel  string
		DebugMode bool
	}{
		LogLevel:  "DEBUG",
		DebugMode: true,
	}

	// Create logger using a config that satisfies the interface
	testLogger := createTestLogger(testConfig)

	// Create test config with very long timeout for test stability
	testRegistryConfig := &RegistryConfig{
		CacheTTL:                 30,
		DefaultTimeoutThreshold:  3600, // 1 hour - very long for tests
		DefaultEvictionThreshold: 7200, // 2 hours
		EnableResponseCache:      false,
	}

	// Create and return EntService
	return NewEntService(entDB, testRegistryConfig, testLogger)
}

// loadTestJSON loads test JSON data from testdata directory
func loadTestJSON(t *testing.T, filename string) map[string]interface{} {
	path := filepath.Join("testdata", "agent_registration", filename)
	data, err := ioutil.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to load test JSON %s: %v", filename, err)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		t.Fatalf("Failed to unmarshal test JSON %s: %v", filename, err)
	}

	return result
}

// convertToServiceRequest converts test JSON to AgentRegistrationRequest
func convertToServiceRequest(jsonData map[string]interface{}) *AgentRegistrationRequest {
	agentID, _ := jsonData["agent_id"].(string)
	timestamp, _ := jsonData["timestamp"].(string)

	// Extract metadata from the JSON
	metadata := make(map[string]interface{})
	for k, v := range jsonData {
		if k != "agent_id" && k != "timestamp" {
			metadata[k] = v
		}
	}

	return &AgentRegistrationRequest{
		AgentID:   agentID,
		Metadata:  metadata,
		Timestamp: timestamp,
	}
}

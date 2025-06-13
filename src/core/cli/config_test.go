package cli

import (
	"os"
	"testing"

	"github.com/spf13/cobra"
)

func TestDefaultConfig(t *testing.T) {
	config := DefaultConfig()

	// Test default values match the specification
	if config.RegistryPort != 8000 {
		t.Errorf("Expected RegistryPort 8000, got %d", config.RegistryPort)
	}
	if config.RegistryHost != "localhost" {
		t.Errorf("Expected RegistryHost 'localhost', got '%s'", config.RegistryHost)
	}
	if config.DBPath != "./dev_registry.db" {
		t.Errorf("Expected DBPath './dev_registry.db', got '%s'", config.DBPath)
	}
	if config.LogLevel != "INFO" {
		t.Errorf("Expected LogLevel 'INFO', got '%s'", config.LogLevel)
	}
	if config.HealthCheckInterval != 30 {
		t.Errorf("Expected HealthCheckInterval 30, got %d", config.HealthCheckInterval)
	}
	if !config.AutoRestart {
		t.Error("Expected AutoRestart to be true")
	}
	if !config.WatchFiles {
		t.Error("Expected WatchFiles to be true")
	}
	if config.DebugMode {
		t.Error("Expected DebugMode to be false")
	}
	if config.Version != ConfigVersion {
		t.Errorf("Expected Version '%s', got '%s'", ConfigVersion, config.Version)
	}
}

func TestEnvironmentVariableLoading(t *testing.T) {
	// Set test environment variables
	envVars := map[string]string{
		"MCP_MESH_REGISTRY_PORT":         "9090",
		"MCP_MESH_REGISTRY_HOST":         "testhost",
		"MCP_MESH_DB_PATH":               "/test/path.db",
		"MCP_MESH_LOG_LEVEL":             "DEBUG",
		"MCP_MESH_HEALTH_CHECK_INTERVAL": "60",
		"MCP_MESH_AUTO_RESTART":          "false",
		"MCP_MESH_WATCH_FILES":           "false",
		"MCP_MESH_DEBUG_MODE":            "true",
		"MCP_MESH_STARTUP_TIMEOUT":       "45",
		"MCP_MESH_SHUTDOWN_TIMEOUT":      "45",
		"MCP_MESH_ENABLE_BACKGROUND":     "true",
		"MCP_MESH_PID_FILE":              "/test/test.pid",
	}

	// Set environment variables
	for key, value := range envVars {
		os.Setenv(key, value)
	}
	defer func() {
		// Clean up environment variables
		for key := range envVars {
			os.Unsetenv(key)
		}
	}()

	config := DefaultConfig()
	loadFromEnvironment(config)

	// Test that environment variables were loaded correctly
	if config.RegistryPort != 9090 {
		t.Errorf("Expected RegistryPort 9090, got %d", config.RegistryPort)
	}
	if config.RegistryHost != "testhost" {
		t.Errorf("Expected RegistryHost 'testhost', got '%s'", config.RegistryHost)
	}
	if config.DBPath != "/test/path.db" {
		t.Errorf("Expected DBPath '/test/path.db', got '%s'", config.DBPath)
	}
	if config.LogLevel != "DEBUG" {
		t.Errorf("Expected LogLevel 'DEBUG', got '%s'", config.LogLevel)
	}
	if config.HealthCheckInterval != 60 {
		t.Errorf("Expected HealthCheckInterval 60, got %d", config.HealthCheckInterval)
	}
	if config.AutoRestart {
		t.Error("Expected AutoRestart to be false")
	}
	if config.WatchFiles {
		t.Error("Expected WatchFiles to be false")
	}
	if !config.DebugMode {
		t.Error("Expected DebugMode to be true")
	}
	if config.StartupTimeout != 45 {
		t.Errorf("Expected StartupTimeout 45, got %d", config.StartupTimeout)
	}
	if config.ShutdownTimeout != 45 {
		t.Errorf("Expected ShutdownTimeout 45, got %d", config.ShutdownTimeout)
	}
	if !config.EnableBackground {
		t.Error("Expected EnableBackground to be true")
	}
	if config.PIDFile != "/test/test.pid" {
		t.Errorf("Expected PIDFile '/test/test.pid', got '%s'", config.PIDFile)
	}
}

func TestParseBoolEnv(t *testing.T) {
	testCases := []struct {
		input    string
		expected bool
	}{
		{"true", true},
		{"TRUE", true},
		{"True", true},
		{"1", true},
		{"yes", true},
		{"YES", true},
		{"on", true},
		{"ON", true},
		{"t", true},
		{"T", true},
		{"y", true},
		{"Y", true},
		{"false", false},
		{"FALSE", false},
		{"False", false},
		{"0", false},
		{"no", false},
		{"NO", false},
		{"off", false},
		{"OFF", false},
		{"f", false},
		{"F", false},
		{"n", false},
		{"N", false},
		{"invalid", false},
		{"", false},
	}

	for _, tc := range testCases {
		result := parseBoolEnv(tc.input)
		if result != tc.expected {
			t.Errorf("parseBoolEnv(%s) = %v, expected %v", tc.input, result, tc.expected)
		}
	}
}

func TestConfigValidation(t *testing.T) {
	config := DefaultConfig()

	// Test valid configuration
	if err := config.Validate(); err != nil {
		t.Errorf("Valid configuration failed validation: %v", err)
	}

	// Test invalid port
	config.RegistryPort = 0
	if err := config.Validate(); err == nil {
		t.Error("Expected validation error for invalid port")
	}
	config.RegistryPort = 8000 // Reset

	// Test invalid host
	config.RegistryHost = ""
	if err := config.Validate(); err == nil {
		t.Error("Expected validation error for empty host")
	}
	config.RegistryHost = "localhost" // Reset

	// Test invalid log level
	config.LogLevel = "INVALID"
	if err := config.Validate(); err == nil {
		t.Error("Expected validation error for invalid log level")
	}
	config.LogLevel = "INFO" // Reset

	// Test invalid health check interval
	config.HealthCheckInterval = 0
	if err := config.Validate(); err == nil {
		t.Error("Expected validation error for invalid health check interval")
	}
	config.HealthCheckInterval = 30 // Reset
}

func TestConfigClone(t *testing.T) {
	original := DefaultConfig()
	original.RegistryPort = 9090
	original.DebugMode = true

	cloned := original.Clone()

	// Test that values are copied
	if cloned.RegistryPort != 9090 {
		t.Error("Cloned config doesn't match original")
	}
	if !cloned.DebugMode {
		t.Error("Cloned config doesn't match original")
	}

	// Test that it's a deep copy
	cloned.RegistryPort = 8080
	if original.RegistryPort == 8080 {
		t.Error("Clone is not independent of original")
	}
}

func TestApplyCliFlags(t *testing.T) {
	config := DefaultConfig()

	// Create a mock command with flags
	cmd := &cobra.Command{}
	cmd.Flags().Int("registry-port", 0, "")
	cmd.Flags().String("registry-host", "", "")
	cmd.Flags().String("log-level", "", "")
	cmd.Flags().Bool("debug", false, "")

	// Set some flag values
	cmd.Flags().Set("registry-port", "9090")
	cmd.Flags().Set("registry-host", "newhost")
	cmd.Flags().Set("log-level", "debug")
	cmd.Flags().Set("debug", "true")

	ApplyCliFlags(config, cmd)

	// Test that CLI flags were applied
	if config.RegistryPort != 9090 {
		t.Errorf("Expected RegistryPort 9090, got %d", config.RegistryPort)
	}
	if config.RegistryHost != "newhost" {
		t.Errorf("Expected RegistryHost 'newhost', got '%s'", config.RegistryHost)
	}
	if config.LogLevel != "DEBUG" {
		t.Errorf("Expected LogLevel 'DEBUG', got '%s'", config.LogLevel)
	}
	if !config.DebugMode {
		t.Error("Expected DebugMode to be true")
	}
}

func TestGetRegistryURL(t *testing.T) {
	config := DefaultConfig()
	config.RegistryHost = "example.com"
	config.RegistryPort = 9090

	expected := "http://example.com:9090"
	actual := config.GetRegistryURL()

	if actual != expected {
		t.Errorf("Expected URL '%s', got '%s'", expected, actual)
	}
}

func TestThreadSafety(t *testing.T) {
	config := DefaultConfig()

	// Test concurrent access
	done := make(chan bool, 2)

	go func() {
		for i := 0; i < 100; i++ {
			config.GetRegistryURL()
		}
		done <- true
	}()

	go func() {
		for i := 0; i < 100; i++ {
			cmd := &cobra.Command{}
			cmd.Flags().Int("registry-port", 8081, "")
			cmd.Flags().Set("registry-port", "8081")
			ApplyCliFlags(config, cmd)
		}
		done <- true
	}()

	// Wait for both goroutines to complete
	<-done
	<-done

	// If we get here without a race condition, the test passes
}

func TestConfigMigration(t *testing.T) {
	config := DefaultConfig()
	config.Version = "0.1.0"

	err := config.Migrate()
	if err != nil {
		t.Errorf("Migration failed: %v", err)
	}

	if config.Version != ConfigVersion {
		t.Errorf("Expected version '%s' after migration, got '%s'", ConfigVersion, config.Version)
	}
}

func TestValidateEnvironmentVariable(t *testing.T) {
	// Test valid cases
	if err := ValidateEnvironmentVariable("MCP_MESH_REGISTRY_PORT", "8080"); err != nil {
		t.Errorf("Valid port should not return error: %v", err)
	}

	if err := ValidateEnvironmentVariable("MCP_MESH_LOG_LEVEL", "INFO"); err != nil {
		t.Errorf("Valid log level should not return error: %v", err)
	}

	// Test invalid cases
	if err := ValidateEnvironmentVariable("MCP_MESH_REGISTRY_PORT", "invalid"); err == nil {
		t.Error("Invalid port should return error")
	}

	if err := ValidateEnvironmentVariable("MCP_MESH_REGISTRY_PORT", "70000"); err == nil {
		t.Error("Port out of range should return error")
	}

	if err := ValidateEnvironmentVariable("MCP_MESH_LOG_LEVEL", "INVALID"); err == nil {
		t.Error("Invalid log level should return error")
	}

	if err := ValidateEnvironmentVariable("MCP_MESH_HEALTH_CHECK_INTERVAL", "0"); err == nil {
		t.Error("Zero interval should return error")
	}
}

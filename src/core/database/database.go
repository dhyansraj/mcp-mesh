package database

import (
	"database/sql"
	"fmt"
	"log"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// Config holds database configuration - MUST match Python DatabaseConfig exactly
type Config struct {
	DatabaseURL        string `env:"DATABASE_URL" envDefault:"mcp_mesh_registry.db"`
	ConnectionTimeout  int    `env:"DB_CONNECTION_TIMEOUT" envDefault:"30"`
	BusyTimeout        int    `env:"DB_BUSY_TIMEOUT" envDefault:"5000"`
	JournalMode        string `env:"DB_JOURNAL_MODE" envDefault:"WAL"`
	Synchronous        string `env:"DB_SYNCHRONOUS" envDefault:"NORMAL"`
	CacheSize          int    `env:"DB_CACHE_SIZE" envDefault:"10000"`
	EnableForeignKeys  bool   `env:"DB_ENABLE_FOREIGN_KEYS" envDefault:"true"`
	MaxOpenConnections int    `env:"DB_MAX_OPEN_CONNECTIONS" envDefault:"25"`
	MaxIdleConnections int    `env:"DB_MAX_IDLE_CONNECTIONS" envDefault:"5"`
	ConnMaxLifetime    int    `env:"DB_CONN_MAX_LIFETIME" envDefault:"300"` // seconds
}

// Database wraps sql.DB instance with MCP Mesh specific methods
type Database struct {
	*sql.DB
	config *Config
}

// Initialize creates and configures the database connection
// MUST maintain identical behavior to Python RegistryDatabase.initialize()
func Initialize(config *Config) (*Database, error) {
	if config == nil {
		config = &Config{
			DatabaseURL:        "mcp_mesh_registry.db",
			ConnectionTimeout:  30,
			BusyTimeout:        5000,
			JournalMode:        "WAL",
			Synchronous:        "NORMAL",
			CacheSize:          10000,
			EnableForeignKeys:  true,
			MaxOpenConnections: 25,
			MaxIdleConnections: 5,
			ConnMaxLifetime:    300,
		}
	}

	var driverName, dataSourceName string

	// Determine database type from URL (same logic as Python)
	if strings.HasPrefix(config.DatabaseURL, "postgres://") || strings.HasPrefix(config.DatabaseURL, "postgresql://") {
		// PostgreSQL for production
		driverName = "postgres"
		dataSourceName = config.DatabaseURL
	} else {
		// SQLite for development (default)
		driverName = "sqlite3"
		dataSourceName = config.DatabaseURL
	}

	// Open database connection
	sqlDB, err := sql.Open(driverName, dataSourceName)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	// Test the connection
	if err := sqlDB.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	// Configure connection pool (matches Python connection pool settings)
	sqlDB.SetMaxOpenConns(config.MaxOpenConnections)
	sqlDB.SetMaxIdleConns(config.MaxIdleConnections)
	sqlDB.SetConnMaxLifetime(time.Duration(config.ConnMaxLifetime) * time.Second)

	database := &Database{
		DB:     sqlDB,
		config: config,
	}

	// SQLite-specific configuration (matches Python PRAGMA settings)
	if strings.Contains(config.DatabaseURL, ".db") || !strings.Contains(config.DatabaseURL, "://") {
		if config.EnableForeignKeys {
			database.Exec("PRAGMA foreign_keys = ON")
		}
		database.Exec(fmt.Sprintf("PRAGMA busy_timeout = %d", config.BusyTimeout))
		database.Exec(fmt.Sprintf("PRAGMA journal_mode = %s", config.JournalMode))
		database.Exec(fmt.Sprintf("PRAGMA synchronous = %s", config.Synchronous))
		database.Exec(fmt.Sprintf("PRAGMA cache_size = -%d", config.CacheSize))
	}

	// Initialize schema using manual SQL
	if err := database.initializeSchemaManual(); err != nil {
		return nil, fmt.Errorf("failed to initialize schema: %w", err)
	}

	return database, nil
}

// initializeSchema creates all tables and indexes (OLD - for reference)
// MUST match Python DatabaseSchema.SCHEMA_SQL and INDEXES exactly
func (db *Database) initializeSchemaManual() error {
	// Create tables manually to avoid GORM association issues
	schemas := []string{
		`CREATE TABLE IF NOT EXISTS schema_version (
			version INTEGER PRIMARY KEY,
			applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)`,

		`CREATE TABLE IF NOT EXISTS agents (
			id TEXT PRIMARY KEY,
			name TEXT NOT NULL,
			namespace TEXT NOT NULL DEFAULT 'default',
			endpoint TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'pending',
			labels TEXT DEFAULT '{}',
			annotations TEXT DEFAULT '{}',
			created_at TIMESTAMP NOT NULL,
			updated_at TIMESTAMP NOT NULL,
			resource_version TEXT NOT NULL,
			last_heartbeat TIMESTAMP,
			health_interval INTEGER DEFAULT 30,
			timeout_threshold INTEGER DEFAULT 60,
			eviction_threshold INTEGER DEFAULT 120,
			agent_type TEXT DEFAULT 'mesh-agent',
			config TEXT DEFAULT '{}',
			security_context TEXT,
			dependencies TEXT DEFAULT '[]'
		)`,

		`CREATE TABLE IF NOT EXISTS tools (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			agent_id TEXT NOT NULL,
			name TEXT NOT NULL,
			capability TEXT NOT NULL,
			version TEXT DEFAULT '1.0.0',
			dependencies TEXT DEFAULT '[]',
			config TEXT DEFAULT '{}',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
			UNIQUE(agent_id, name)
		)`,

		`CREATE TABLE IF NOT EXISTS agent_health (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			agent_id TEXT NOT NULL,
			status TEXT NOT NULL,
			timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			checks TEXT DEFAULT '{}',
			errors TEXT DEFAULT '[]',
			uptime_seconds INTEGER DEFAULT 0,
			metadata TEXT DEFAULT '{}',
			FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
		)`,

		`CREATE TABLE IF NOT EXISTS registry_events (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			event_type TEXT NOT NULL,
			agent_id TEXT NOT NULL,
			timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			resource_version TEXT NOT NULL,
			data TEXT,
			source TEXT DEFAULT 'registry',
			metadata TEXT DEFAULT '{}'
		)`,

		`CREATE TABLE IF NOT EXISTS service_contracts (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			agent_id TEXT NOT NULL,
			service_name TEXT NOT NULL,
			service_version TEXT NOT NULL DEFAULT '1.0.0',
			description TEXT,
			contract_version TEXT NOT NULL DEFAULT '1.0.0',
			compatibility_level TEXT NOT NULL DEFAULT 'strict',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
		)`,

		`CREATE TABLE IF NOT EXISTS method_metadata (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			contract_id INTEGER NOT NULL,
			method_name TEXT NOT NULL,
			signature_data TEXT NOT NULL,
			return_type TEXT,
			is_async BOOLEAN DEFAULT FALSE,
			method_type TEXT DEFAULT 'function',
			docstring TEXT,
			service_version TEXT DEFAULT '1.0.0',
			stability_level TEXT DEFAULT 'stable',
			deprecation_warning TEXT,
			expected_complexity TEXT DEFAULT 'O(1)',
			timeout_hint INTEGER DEFAULT 30,
			resource_requirements TEXT DEFAULT '{}',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (contract_id) REFERENCES service_contracts(id) ON DELETE CASCADE
		)`,

		`CREATE TABLE IF NOT EXISTS method_parameters (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			method_id INTEGER NOT NULL,
			parameter_name TEXT NOT NULL,
			parameter_type TEXT NOT NULL,
			parameter_kind TEXT NOT NULL,
			default_value TEXT,
			annotation TEXT,
			has_default BOOLEAN DEFAULT FALSE,
			is_optional BOOLEAN DEFAULT FALSE,
			position INTEGER NOT NULL,
			FOREIGN KEY (method_id) REFERENCES method_metadata(id) ON DELETE CASCADE
		)`,

		`CREATE TABLE IF NOT EXISTS method_capabilities (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			method_id INTEGER NOT NULL,
			capability_name TEXT NOT NULL,
			capability_id INTEGER,
			FOREIGN KEY (method_id) REFERENCES method_metadata(id) ON DELETE CASCADE
			-- Note: Removed FK to capabilities table since we use tools table instead
		)`,

		`CREATE TABLE IF NOT EXISTS capability_method_mapping (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			capability_id INTEGER NOT NULL,
			method_id INTEGER NOT NULL,
			mapping_type TEXT DEFAULT 'direct',
			priority INTEGER DEFAULT 0,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			-- Note: Removed FK to capabilities table since we use tools table instead
			FOREIGN KEY (method_id) REFERENCES method_metadata(id) ON DELETE CASCADE
		)`,
	}

	for _, schema := range schemas {
		if _, err := db.Exec(schema); err != nil {
			return fmt.Errorf("failed to create table: %w", err)
		}
	}

	// Create additional indexes that match Python DatabaseSchema.INDEXES exactly
	indexes := []string{
		// Agent discovery optimization
		"CREATE INDEX IF NOT EXISTS idx_agents_namespace ON agents(namespace)",
		"CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)",
		"CREATE INDEX IF NOT EXISTS idx_agents_updated ON agents(updated_at)",
		"CREATE INDEX IF NOT EXISTS idx_agents_heartbeat ON agents(last_heartbeat)",

		// Capability discovery optimization
		"CREATE INDEX IF NOT EXISTS idx_tools_capability ON tools(capability)",
		"CREATE INDEX IF NOT EXISTS idx_tools_agent ON tools(agent_id)",
		"CREATE INDEX IF NOT EXISTS idx_tools_composite ON tools(capability, agent_id)",

		// Health monitoring optimization
		"CREATE INDEX IF NOT EXISTS idx_health_agent ON agent_health(agent_id)",
		"CREATE INDEX IF NOT EXISTS idx_health_timestamp ON agent_health(timestamp)",
		"CREATE INDEX IF NOT EXISTS idx_health_status ON agent_health(agent_id, timestamp)",

		// Event history optimization
		"CREATE INDEX IF NOT EXISTS idx_events_agent ON registry_events(agent_id)",
		"CREATE INDEX IF NOT EXISTS idx_events_timestamp ON registry_events(timestamp)",
		"CREATE INDEX IF NOT EXISTS idx_events_type ON registry_events(event_type, timestamp)",

		// Service contract optimization
		"CREATE INDEX IF NOT EXISTS idx_contracts_agent ON service_contracts(agent_id)",
		"CREATE INDEX IF NOT EXISTS idx_contracts_service ON service_contracts(service_name, service_version)",
		"CREATE INDEX IF NOT EXISTS idx_contracts_composite ON service_contracts(agent_id, service_name)",

		// Method metadata optimization
		"CREATE INDEX IF NOT EXISTS idx_methods_contract ON method_metadata(contract_id)",
		"CREATE INDEX IF NOT EXISTS idx_methods_name ON method_metadata(method_name)",
		"CREATE INDEX IF NOT EXISTS idx_methods_composite ON method_metadata(contract_id, method_name)",
		"CREATE INDEX IF NOT EXISTS idx_methods_stability ON method_metadata(stability_level)",

		// Parameter optimization
		"CREATE INDEX IF NOT EXISTS idx_parameters_method ON method_parameters(method_id)",
		"CREATE INDEX IF NOT EXISTS idx_parameters_type ON method_parameters(parameter_type)",
		"CREATE INDEX IF NOT EXISTS idx_parameters_position ON method_parameters(method_id, position)",

		// Method capabilities optimization
		"CREATE INDEX IF NOT EXISTS idx_method_caps_method ON method_capabilities(method_id)",
		"CREATE INDEX IF NOT EXISTS idx_method_caps_capability ON method_capabilities(capability_name)",
		"CREATE INDEX IF NOT EXISTS idx_method_caps_composite ON method_capabilities(capability_name, method_id)",

		// Capability-method mapping optimization
		"CREATE INDEX IF NOT EXISTS idx_cap_mapping_capability ON capability_method_mapping(capability_id)",
		"CREATE INDEX IF NOT EXISTS idx_cap_mapping_method ON capability_method_mapping(method_id)",
		"CREATE INDEX IF NOT EXISTS idx_cap_mapping_type ON capability_method_mapping(mapping_type)",
		"CREATE INDEX IF NOT EXISTS idx_cap_mapping_priority ON capability_method_mapping(capability_id, priority)",
	}

	for _, indexSQL := range indexes {
		if _, err := db.Exec(indexSQL); err != nil {
			log.Printf("Warning: Failed to create index: %s - %v", indexSQL, err)
			// Don't fail initialization for index creation errors
		}
	}

	// Check and update schema version (matches Python migration logic)
	if err := db.checkSchemaVersion(); err != nil {
		return fmt.Errorf("failed to check schema version: %w", err)
	}

	return nil
}

// checkSchemaVersion ensures schema is at the correct version
// MUST match Python DatabaseSchema.SCHEMA_VERSION = 2
func (db *Database) checkSchemaVersion() error {
	const currentSchemaVersion = 2

	// Check current schema version
	var currentVersion int
	err := db.QueryRow("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").Scan(&currentVersion)

	if err != nil && err != sql.ErrNoRows {
		return fmt.Errorf("failed to check schema version: %w", err)
	}

	if currentVersion < currentSchemaVersion {
		// Apply migration using raw SQL
		_, err := db.Exec("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
			currentSchemaVersion, time.Now().UTC())
		if err != nil {
			return fmt.Errorf("failed to update schema version: %w", err)
		}

		log.Printf("Schema updated from version %d to %d", currentVersion, currentSchemaVersion)
	}

	return nil
}

// Close closes the database connection
func (db *Database) Close() error {
	return db.DB.Close()
}

// GetStats returns database statistics (matches Python get_database_stats)
func (db *Database) GetStats() (map[string]interface{}, error) {
	stats := make(map[string]interface{})

	// Agent counts by status
	rows, err := db.Query("SELECT status, COUNT(*) as count FROM agents GROUP BY status")
	if err != nil {
		return nil, fmt.Errorf("failed to get agent status counts: %w", err)
	}
	defer rows.Close()

	agentsByStatus := make(map[string]int64)
	for rows.Next() {
		var status string
		var count int64
		if err := rows.Scan(&status, &count); err != nil {
			return nil, fmt.Errorf("failed to scan agent status counts: %w", err)
		}
		agentsByStatus[status] = count
	}
	stats["agents_by_status"] = agentsByStatus

	// Unique capabilities count (using tools table instead of capabilities)
	var uniqueCapabilities int64
	err = db.QueryRow("SELECT COUNT(DISTINCT capability) FROM tools").Scan(&uniqueCapabilities)
	if err != nil {
		return nil, fmt.Errorf("failed to get unique capabilities count: %w", err)
	}
	stats["unique_capabilities"] = uniqueCapabilities

	// Health events in last hour
	oneHourAgo := time.Now().UTC().Add(-time.Hour)
	var healthEventsLastHour int64
	err = db.QueryRow("SELECT COUNT(*) FROM agent_health WHERE timestamp > ?", oneHourAgo).Scan(&healthEventsLastHour)
	if err != nil {
		return nil, fmt.Errorf("failed to get health events count: %w", err)
	}
	stats["health_events_last_hour"] = healthEventsLastHour

	return stats, nil
}

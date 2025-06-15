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

	// Initialize schema using current schema
	if err := database.initializeSchema(); err != nil {
		return nil, fmt.Errorf("failed to initialize schema: %w", err)
	}

	return database, nil
}

// initializeSchema creates all tables and indexes (OLD - for reference)
// MUST match Python DatabaseSchema.SCHEMA_SQL and INDEXES exactly
func (db *Database) initializeSchema() error {
	// Create tables manually to avoid GORM association issues
	schemas := []string{
		`CREATE TABLE IF NOT EXISTS schema_version (
			version INTEGER PRIMARY KEY,
			applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)`,

		`CREATE TABLE IF NOT EXISTS agents (
			agent_id TEXT PRIMARY KEY,
			agent_type TEXT NOT NULL DEFAULT 'mcp_agent',
			name TEXT NOT NULL,
			version TEXT,
			http_host TEXT,
			http_port INTEGER,
			namespace TEXT DEFAULT 'default',

			-- Dependency tracking (computed fields)
			total_dependencies INTEGER DEFAULT 0,
			dependencies_resolved INTEGER DEFAULT 0,

			-- Registry-controlled timestamps (source of truth)
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)`,

		// 2. CAPABILITIES table - What each agent provides
		`CREATE TABLE IF NOT EXISTS capabilities (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			agent_id TEXT NOT NULL,
			function_name TEXT NOT NULL,               -- "smart_greet", "get_weather_report"
			capability TEXT NOT NULL,                  -- "personalized_greeting", "weather_report"
			version TEXT DEFAULT '1.0.0',
			description TEXT,
			tags TEXT DEFAULT '[]',                    -- JSON array: ["prod", "ml", "gpu"]

			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

			FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE,
			UNIQUE(agent_id, function_name)
		)`,

		// 3. REGISTRY_EVENTS table - Audit trail
		`CREATE TABLE IF NOT EXISTS registry_events (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			event_type TEXT NOT NULL,                  -- 'register', 'heartbeat', 'expire'
			agent_id TEXT NOT NULL,
			function_name TEXT,                        -- NULL for agent-level events
			timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			data TEXT DEFAULT '{}'                     -- JSON event data
		)`,

	}

	for _, schema := range schemas {
		if _, err := db.Exec(schema); err != nil {
			return fmt.Errorf("failed to create table: %w", err)
		}
	}

	// Create performance indexes for current schema
	indexes := []string{
		// Agent indexes
		"CREATE INDEX IF NOT EXISTS idx_agents_namespace ON agents(namespace)",
		"CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(agent_type)",
		"CREATE INDEX IF NOT EXISTS idx_agents_updated_at ON agents(updated_at)",

		// Capability indexes
		"CREATE INDEX IF NOT EXISTS idx_capabilities_capability ON capabilities(capability)",
		"CREATE INDEX IF NOT EXISTS idx_capabilities_agent ON capabilities(agent_id)",
		"CREATE INDEX IF NOT EXISTS idx_capabilities_function ON capabilities(function_name)",

		// Event indexes
		"CREATE INDEX IF NOT EXISTS idx_events_agent ON registry_events(agent_id)",
		"CREATE INDEX IF NOT EXISTS idx_events_timestamp ON registry_events(timestamp)",
		"CREATE INDEX IF NOT EXISTS idx_events_type ON registry_events(event_type)",
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

	// Total agent count
	var totalAgents int64
	err := db.QueryRow("SELECT COUNT(*) FROM agents").Scan(&totalAgents)
	if err != nil {
		return nil, fmt.Errorf("failed to get total agent count: %w", err)
	}
	stats["total_agents"] = totalAgents

	// Agent counts by namespace
	rows, err := db.Query("SELECT namespace, COUNT(*) as count FROM agents GROUP BY namespace")
	if err != nil {
		return nil, fmt.Errorf("failed to get agent namespace counts: %w", err)
	}
	defer rows.Close()

	agentsByNamespace := make(map[string]int64)
	for rows.Next() {
		var namespace string
		var count int64
		if err := rows.Scan(&namespace, &count); err != nil {
			return nil, fmt.Errorf("failed to scan agent namespace counts: %w", err)
		}
		agentsByNamespace[namespace] = count
	}
	stats["agents_by_namespace"] = agentsByNamespace

	// Unique capabilities count (using capabilities table)
	var uniqueCapabilities int64
	err = db.QueryRow("SELECT COUNT(DISTINCT capability) FROM capabilities").Scan(&uniqueCapabilities)
	if err != nil {
		return nil, fmt.Errorf("failed to get unique capabilities count: %w", err)
	}
	stats["unique_capabilities"] = uniqueCapabilities

	// Recent registry events count (last hour)
	oneHourAgo := time.Now().UTC().Add(-time.Hour)
	var recentEvents int64
	err = db.QueryRow("SELECT COUNT(*) FROM registry_events WHERE timestamp > ?", oneHourAgo).Scan(&recentEvents)
	if err != nil {
		return nil, fmt.Errorf("failed to get recent events count: %w", err)
	}
	stats["recent_events_last_hour"] = recentEvents

	return stats, nil
}

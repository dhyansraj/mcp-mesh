package database

import (
	"context"
	"fmt"
	"log"
	"path/filepath"
	"strings"
	"time"

	"entgo.io/ent/dialect/sql"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/migrate"
	"mcp-mesh/src/core/ent/registryevent"

	_ "github.com/lib/pq"
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

// EntDatabase wraps the Ent client with MCP Mesh specific methods
type EntDatabase struct {
	*ent.Client
	config   *Config
	driverName string
	dataSourceName string
}

// InitializeEnt creates and configures the Ent database client
// This replaces the Initialize function in database.go with Ent-based implementation
func InitializeEnt(config *Config, enableDebugLogging bool) (*EntDatabase, error) {
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

	// Determine database type from URL (same logic as Python/original)
	if strings.HasPrefix(config.DatabaseURL, "postgres://") || strings.HasPrefix(config.DatabaseURL, "postgresql://") {
		// PostgreSQL for production
		driverName = "postgres"
		dataSourceName = config.DatabaseURL
	} else {
		// SQLite for development (default)
		driverName = "sqlite3"

		// Convert relative SQLite paths to absolute paths to ensure consistent database location
		// regardless of working directory
		sqlitePath := config.DatabaseURL
		if !filepath.IsAbs(sqlitePath) && !strings.Contains(sqlitePath, ":memory:") {
			// Make relative paths absolute, but preserve special SQLite URLs like ":memory:"
			var err error
			sqlitePath, err = filepath.Abs(sqlitePath)
			if err != nil {
				return nil, fmt.Errorf("failed to resolve absolute path for SQLite database: %w", err)
			}
		}

		dataSourceName = sqlitePath

		// Add foreign key support for SQLite if not already present
		if !strings.Contains(dataSourceName, "_fk=") {
			if strings.Contains(dataSourceName, "?") {
				dataSourceName += "&_fk=1"
			} else {
				dataSourceName += "?_fk=1"
			}
		}
	}

	// Create Ent driver with connection pool configuration
	drv, err := sql.Open(driverName, dataSourceName)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Configure connection pool (matches original settings)
	db := drv.DB()
	db.SetMaxOpenConns(config.MaxOpenConnections)
	db.SetMaxIdleConns(config.MaxIdleConnections)
	db.SetConnMaxLifetime(time.Duration(config.ConnMaxLifetime) * time.Second)

	// Test the connection
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	// SQLite-specific configuration (matches original PRAGMA settings)
	if driverName == "sqlite3" {
		ctx := context.Background()

		if config.EnableForeignKeys {
			if _, err := db.ExecContext(ctx, "PRAGMA foreign_keys = ON"); err != nil {
				log.Printf("Warning: Failed to enable foreign keys: %v", err)
			}
		}

		pragmas := []string{
			fmt.Sprintf("PRAGMA busy_timeout = %d", config.BusyTimeout),
			fmt.Sprintf("PRAGMA journal_mode = %s", config.JournalMode),
			fmt.Sprintf("PRAGMA synchronous = %s", config.Synchronous),
			fmt.Sprintf("PRAGMA cache_size = -%d", config.CacheSize),
		}

		for _, pragma := range pragmas {
			if _, err := db.ExecContext(ctx, pragma); err != nil {
				log.Printf("Warning: Failed to execute %s: %v", pragma, err)
			}
		}
	}

	// Create Ent client with the configured driver
	var client *ent.Client
	if enableDebugLogging {
		// Enable SQL query logging only in debug mode
		client = ent.NewClient(ent.Driver(drv), ent.Debug())
	} else {
		// Disable SQL query logging in production
		client = ent.NewClient(ent.Driver(drv))
	}

	// Initialize schema using Ent migrations
	ctx := context.Background()
	if err := client.Schema.Create(
		ctx,
		migrate.WithGlobalUniqueID(true),
		migrate.WithDropIndex(true),
		migrate.WithDropColumn(true),
	); err != nil {
		return nil, fmt.Errorf("failed to create schema: %w", err)
	}

	// Note: Using standard log here since we don't have structured logger in this package
	// The main application will show the database info via structured logging
	if enableDebugLogging {
		log.Printf("Ent database initialized successfully with %s driver (SQL queries will be logged)", driverName)
	}

	return &EntDatabase{
		Client:         client,
		config:         config,
		driverName:     driverName,
		dataSourceName: dataSourceName,
	}, nil
}

// IsPostgreSQL returns true if the database is PostgreSQL
func (db *EntDatabase) IsPostgreSQL() bool {
	return db.driverName == "postgres"
}

// IsSQLite returns true if the database is SQLite
func (db *EntDatabase) IsSQLite() bool {
	return db.driverName == "sqlite3"
}

// Close closes the database connection
func (db *EntDatabase) Close() error {
	return db.Client.Close()
}

// GetEntClient returns the underlying Ent client for direct access
func (db *EntDatabase) GetEntClient() *ent.Client {
	return db.Client
}

// GetStats returns database statistics using Ent queries
// This replaces the GetStats method from the original database.go
func (db *EntDatabase) GetStats() (map[string]interface{}, error) {
	ctx := context.Background()
	stats := make(map[string]interface{})

	// Total agent count
	totalAgents, err := db.Agent.Query().Count(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get total agent count: %w", err)
	}
	stats["total_agents"] = totalAgents

	// Agent counts by namespace - simplified implementation for now
	// TODO: Implement proper GroupBy aggregation when needed
	agentsByNamespace := make(map[string]int)
	agents, err := db.Agent.Query().All(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get agents for namespace counting: %w", err)
	}
	for _, agent := range agents {
		agentsByNamespace[agent.Namespace]++
	}
	stats["agents_by_namespace"] = agentsByNamespace

	// Unique capabilities count - count distinct capability values
	capabilities, err := db.Capability.Query().All(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get capabilities: %w", err)
	}
	uniqueCapabilitiesSet := make(map[string]bool)
	for _, cap := range capabilities {
		uniqueCapabilitiesSet[cap.Capability] = true
	}
	stats["unique_capabilities"] = len(uniqueCapabilitiesSet)

	// Recent registry events count (last hour)
	oneHourAgo := time.Now().UTC().Add(-time.Hour)
	recentEvents, err := db.RegistryEvent.Query().
		Where(registryevent.TimestampGT(oneHourAgo)).
		Count(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get recent events count: %w", err)
	}
	stats["recent_events_last_hour"] = recentEvents

	return stats, nil
}

// Transaction executes a function within a database transaction
func (db *EntDatabase) Transaction(ctx context.Context, fn func(*ent.Tx) error) error {
	tx, err := db.Tx(ctx)
	if err != nil {
		return err
	}
	defer func() {
		if v := recover(); v != nil {
			tx.Rollback()
			panic(v)
		}
	}()

	if err := fn(tx); err != nil {
		if rerr := tx.Rollback(); rerr != nil {
			return fmt.Errorf("rolling back transaction: %w", rerr)
		}
		return err
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("committing transaction: %w", err)
	}

	return nil
}

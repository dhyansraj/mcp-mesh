package registry

import (
	"database/sql"
	"log"
	"sync"
	"time"

	"mcp-mesh/internal/database"
)

// HealthMonitor provides passive health monitoring functionality
// MUST match Python health monitoring behavior exactly
type HealthMonitor struct {
	service       *Service
	db            *database.Database
	ticker        *time.Ticker
	stopCh        chan struct{}
	wg            sync.WaitGroup
	isRunning     bool
	mutex         sync.RWMutex
	
	// Configuration matching Python defaults
	monitoringInterval   time.Duration // Default: 10 seconds (Python health check interval)
	defaultTimeout       time.Duration // Default: 60 seconds (marks as degraded)
	defaultEviction      time.Duration // Default: 120 seconds (marks as expired)
	
	// Type-specific thresholds matching Python implementation
	typeThresholds map[string]TypeThresholds
}

// TypeThresholds holds timeout and eviction thresholds for specific agent types
// MUST match Python type-specific configurations exactly
type TypeThresholds struct {
	TimeoutThreshold  time.Duration
	EvictionThreshold time.Duration
}

// NewHealthMonitor creates a new health monitor instance
// Matches Python HealthMonitor.__init__ behavior exactly
func NewHealthMonitor(service *Service, db *database.Database) *HealthMonitor {
	hm := &HealthMonitor{
		service:            service,
		db:                 db,
		stopCh:             make(chan struct{}),
		monitoringInterval: 10 * time.Second, // Python: 10 seconds
		defaultTimeout:     60 * time.Second, // Python: 60 seconds
		defaultEviction:    120 * time.Second, // Python: 120 seconds
		typeThresholds:     make(map[string]TypeThresholds),
	}
	
	// Initialize type-specific thresholds matching Python configuration
	hm.typeThresholds["file-agent"] = TypeThresholds{
		TimeoutThreshold:  90 * time.Second,  // Python: timeout=90s
		EvictionThreshold: 180 * time.Second, // Python: eviction=180s
	}
	hm.typeThresholds["worker"] = TypeThresholds{
		TimeoutThreshold:  45 * time.Second,  // Python: timeout=45s
		EvictionThreshold: 90 * time.Second,  // Python: eviction=90s
	}
	hm.typeThresholds["critical"] = TypeThresholds{
		TimeoutThreshold:  30 * time.Second,  // Python: timeout=30s
		EvictionThreshold: 60 * time.Second,  // Python: eviction=60s
	}
	hm.typeThresholds["mesh-agent"] = TypeThresholds{
		TimeoutThreshold:  60 * time.Second,  // Python: default timeout
		EvictionThreshold: 120 * time.Second, // Python: default eviction
	}
	
	return hm
}

// Start begins passive health monitoring
// MUST match Python start_health_monitoring behavior exactly
func (hm *HealthMonitor) Start() error {
	hm.mutex.Lock()
	defer hm.mutex.Unlock()
	
	if hm.isRunning {
		return nil // Already running
	}
	
	hm.ticker = time.NewTicker(hm.monitoringInterval)
	hm.isRunning = true
	
	hm.wg.Add(1)
	go hm.monitoringLoop()
	
	log.Printf("Health monitoring started (interval: %v)", hm.monitoringInterval)
	return nil
}

// Stop stops the health monitoring
func (hm *HealthMonitor) Stop() error {
	hm.mutex.Lock()
	defer hm.mutex.Unlock()
	
	if !hm.isRunning {
		return nil // Not running
	}
	
	close(hm.stopCh)
	hm.ticker.Stop()
	hm.isRunning = false
	
	hm.wg.Wait()
	
	log.Printf("Health monitoring stopped")
	return nil
}

// IsRunning returns whether health monitoring is active
func (hm *HealthMonitor) IsRunning() bool {
	hm.mutex.RLock()
	defer hm.mutex.RUnlock()
	return hm.isRunning
}

// monitoringLoop runs the passive health assessment
// MUST match Python _health_monitoring_loop behavior exactly
func (hm *HealthMonitor) monitoringLoop() {
	defer hm.wg.Done()
	
	log.Printf("Starting health monitoring loop")
	
	for {
		select {
		case <-hm.ticker.C:
			if err := hm.assessAgentHealth(); err != nil {
				log.Printf("Error during health assessment: %v", err)
			}
		case <-hm.stopCh:
			log.Printf("Health monitoring loop stopped")
			return
		}
	}
}

// assessAgentHealth performs passive health assessment for all agents
// MUST match Python assess_agent_health behavior exactly
func (hm *HealthMonitor) assessAgentHealth() error {
	now := time.Now().UTC()
	
	// Get all agents for health assessment
	rows, err := hm.db.DB.Query("SELECT id, name, namespace, endpoint, status, labels, annotations, created_at, updated_at, resource_version, last_heartbeat, health_interval, timeout_threshold, eviction_threshold, agent_type, config, security_context, dependencies FROM agents")
	if err != nil {
		return err
	}
	defer rows.Close()

	var agents []database.Agent
	for rows.Next() {
		var agent database.Agent
		var lastHeartbeat sql.NullTime
		var securityContext sql.NullString
		
		err := rows.Scan(
			&agent.ID, &agent.Name, &agent.Namespace, &agent.Endpoint, &agent.Status,
			&agent.Labels, &agent.Annotations, &agent.CreatedAt, &agent.UpdatedAt,
			&agent.ResourceVersion, &lastHeartbeat, &agent.HealthInterval,
			&agent.TimeoutThreshold, &agent.EvictionThreshold, &agent.AgentType,
			&agent.Config, &securityContext, &agent.Dependencies)
		if err != nil {
			return err
		}
		
		if lastHeartbeat.Valid {
			agent.LastHeartbeat = &lastHeartbeat.Time
		}
		if securityContext.Valid {
			agent.SecurityContext = &securityContext.String
		}
		
		agents = append(agents, agent)
	}
	
	statusChanges := 0
	
	// Process each agent (matches Python logic)
	for _, agent := range agents {
		if err := hm.assessSingleAgent(&agent, now); err != nil {
			log.Printf("Error assessing agent %s: %v", agent.ID, err)
			continue
		}
		statusChanges++
	}
	
	if statusChanges > 0 {
		// Invalidate cache when health statuses change (matches Python behavior)
		hm.service.cache.invalidateAll()
	}
	
	return nil
}

// assessSingleAgent assesses health for a single agent
// MUST match Python _assess_single_agent logic exactly
func (hm *HealthMonitor) assessSingleAgent(agent *database.Agent, now time.Time) error {
	// Skip agents that have never sent a heartbeat
	if agent.LastHeartbeat == nil {
		return nil
	}
	
	// Calculate time since last heartbeat
	timeSinceLastSeen := now.Sub(*agent.LastHeartbeat)
	
	// Get thresholds for this agent type
	thresholds := hm.getThresholdsForAgent(agent)
	
	// Determine new status based on time since last heartbeat
	// Matches Python status transition logic exactly
	var newStatus string
	switch {
	case timeSinceLastSeen > thresholds.EvictionThreshold:
		newStatus = "expired"
	case timeSinceLastSeen > thresholds.TimeoutThreshold:
		newStatus = "degraded"
	default:
		newStatus = "healthy"
	}
	
	// Only update if status changed (matches Python optimization)
	if newStatus != agent.Status {
		oldStatus := agent.Status
		
		// Update agent status in database
		if err := hm.updateAgentStatus(agent, newStatus, now); err != nil {
			return err
		}
		
		// Record health event (matches Python _record_health_event)
		if err := hm.recordHealthEvent(agent.ID, newStatus, oldStatus, now); err != nil {
			log.Printf("Failed to record health event for agent %s: %v", agent.ID, err)
		}
		
		// Log status transition (matches Python logging)
		log.Printf("Agent %s status: %s → %s (last_heartbeat: %v ago)", 
			agent.ID, oldStatus, newStatus, timeSinceLastSeen)
	}
	
	return nil
}

// getThresholdsForAgent returns appropriate thresholds for an agent
// MUST match Python threshold selection logic exactly
func (hm *HealthMonitor) getThresholdsForAgent(agent *database.Agent) TypeThresholds {
	// First priority: Agent-specific thresholds from database (matches Python logic)
	if agent.TimeoutThreshold > 0 && agent.EvictionThreshold > 0 {
		return TypeThresholds{
			TimeoutThreshold:  time.Duration(agent.TimeoutThreshold) * time.Second,
			EvictionThreshold: time.Duration(agent.EvictionThreshold) * time.Second,
		}
	}
	
	// Second priority: Type-specific thresholds
	if thresholds, exists := hm.typeThresholds[agent.AgentType]; exists {
		return thresholds
	}
	
	// Fallback: Default thresholds (matches Python fallback)
	return TypeThresholds{
		TimeoutThreshold:  hm.defaultTimeout,
		EvictionThreshold: hm.defaultEviction,
	}
}

// updateAgentStatus updates agent status in database
// MUST match Python database update behavior exactly
func (hm *HealthMonitor) updateAgentStatus(agent *database.Agent, newStatus string, timestamp time.Time) error {
	// Use same update pattern as Python implementation
	updates := map[string]interface{}{
		"status":           newStatus,
		"updated_at":       timestamp,
		"resource_version": timestamp.UnixMilli(), // Matches Python resource versioning
	}
	
	_, err := hm.db.DB.Exec(`
		UPDATE agents SET 
			status = ?, 
			updated_at = ?, 
			resource_version = ?
		WHERE id = ?`,
		updates["status"], updates["updated_at"], updates["resource_version"], agent.ID)
	if err != nil {
		return err
	}
	
	// Update local agent object for consistency
	agent.Status = newStatus
	agent.UpdatedAt = timestamp
	
	return nil
}

// recordHealthEvent records a health status change event
// MUST match Python _record_health_event behavior exactly
func (hm *HealthMonitor) recordHealthEvent(agentID, newStatus, oldStatus string, timestamp time.Time) error {
	healthEvent := database.AgentHealth{
		AgentID:   agentID,
		Status:    newStatus,
		Timestamp: timestamp,
		Metadata:  `{"source": "health_monitor", "event_type": "status_change"}`,
	}
	
	// Add old status to metadata if available
	if oldStatus != "" {
		healthEvent.Metadata = `{"source": "health_monitor", "event_type": "status_change", "old_status": "` + oldStatus + `"}`
	}
	
	_, err := hm.db.DB.Exec(`
		INSERT INTO agent_health (
			agent_id, status, timestamp, metadata
		) VALUES (?, ?, ?, ?)`,
		healthEvent.AgentID, healthEvent.Status, healthEvent.Timestamp, healthEvent.Metadata)
	return err
}

// GetHealthStats returns current health monitoring statistics
// Matches Python get_health_stats method
func (hm *HealthMonitor) GetHealthStats() (map[string]interface{}, error) {
	stats := make(map[string]interface{})
	
	// Count agents by status
	var statusCounts []struct {
		Status string
		Count  int64
	}
	
	rows, err := hm.db.DB.Query("SELECT status, COUNT(*) as count FROM agents GROUP BY status")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var sc struct {
			Status string
			Count  int64
		}
		if err := rows.Scan(&sc.Status, &sc.Count); err != nil {
			return nil, err
		}
		statusCounts = append(statusCounts, sc)
	}
	
	// Build status counts map
	statusMap := make(map[string]int64)
	for _, sc := range statusCounts {
		statusMap[sc.Status] = sc.Count
	}
	
	stats["agent_status_counts"] = statusMap
	stats["monitoring_active"] = hm.IsRunning()
	stats["monitoring_interval_seconds"] = int(hm.monitoringInterval.Seconds())
	stats["default_timeout_seconds"] = int(hm.defaultTimeout.Seconds())
	stats["default_eviction_seconds"] = int(hm.defaultEviction.Seconds())
	stats["timestamp"] = time.Now().UTC().Format(time.RFC3339)
	
	return stats, nil
}

// SetMonitoringInterval updates the monitoring interval
func (hm *HealthMonitor) SetMonitoringInterval(interval time.Duration) {
	hm.mutex.Lock()
	defer hm.mutex.Unlock()
	
	hm.monitoringInterval = interval
	
	if hm.isRunning && hm.ticker != nil {
		hm.ticker.Reset(interval)
		log.Printf("Health monitoring interval updated to %v", interval)
	}
}

// SetTypeThresholds updates thresholds for a specific agent type
func (hm *HealthMonitor) SetTypeThresholds(agentType string, timeout, eviction time.Duration) {
	hm.mutex.Lock()
	defer hm.mutex.Unlock()
	
	hm.typeThresholds[agentType] = TypeThresholds{
		TimeoutThreshold:  timeout,
		EvictionThreshold: eviction,
	}
	
	log.Printf("Updated thresholds for agent type '%s': timeout=%v, eviction=%v", 
		agentType, timeout, eviction)
}
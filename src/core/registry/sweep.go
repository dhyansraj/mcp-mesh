package registry

import (
	"context"
	"fmt"
	"os"
	"sync"
	"time"

	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/dependencyresolution"
	"mcp-mesh/src/core/ent/llmproviderresolution"
	"mcp-mesh/src/core/ent/llmtoolresolution"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"
)

// Internal sweep tunables. Operators get a single env-var knob
// (MCP_MESH_RETENTION); these are deliberately not configurable so the
// surface area stays small.
const (
	sweepInterval    = 5 * time.Minute
	defaultRetention = 1 * time.Hour
	eventMaxRows     = 100_000
)

// SweepConfig holds the configuration for the registry sweep job.
//
// Set Retention to 0 to disable the sweep entirely (forensic escape hatch:
// no goroutine is launched, no agents or events are purged).
type SweepConfig struct {
	Retention time.Duration
}

// LoadSweepConfigFromEnv reads sweep configuration from the environment.
//
// Only MCP_MESH_RETENTION is honored:
//   - unset / empty: defaults to 1h
//   - any time.ParseDuration value (e.g. "2h", "30m"): use that value
//   - "0" / "0s": disables the sweep job entirely
//   - invalid: warn and fall back to default
func LoadSweepConfigFromEnv(log *logger.Logger) SweepConfig {
	cfg := SweepConfig{Retention: defaultRetention}

	if v := os.Getenv("MCP_MESH_RETENTION"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			cfg.Retention = d
		} else if log != nil {
			log.Warning("Invalid MCP_MESH_RETENTION %q, using default %s: %v", v, cfg.Retention, err)
		}
	}

	return cfg
}

// SweepJob purges stale agents and old registry events on a periodic timer.
//
// On each tick the job runs (in order):
//  1. Purge agents in unhealthy/unknown status whose updated_at is older
//     than Retention. Before deleting, dependency_resolution rows where
//     the purged agent is a provider are flipped to status=unavailable so
//     consumer-side state stays consistent.
//  2. If the event row count exceeds the internal hard cap (100,000),
//     delete oldest rows until back under the cap. Events are governed
//     solely by row count, not age.
type SweepJob struct {
	cfg     SweepConfig
	entDB   *database.EntDatabase
	service *EntService
	logger  *logger.Logger

	clock        func() time.Time
	eventMaxRows int

	mu      sync.Mutex
	cancel  context.CancelFunc
	wg      sync.WaitGroup
	running bool
}

// NewSweepJob constructs a SweepJob with the given configuration.
//
// The clock and eventMaxRows are injectable for tests; production callers
// should leave them unset so they default to time.Now (UTC) and the
// internal eventMaxRows constant respectively.
func NewSweepJob(cfg SweepConfig, entDB *database.EntDatabase, service *EntService, log *logger.Logger) *SweepJob {
	return &SweepJob{
		cfg:          cfg,
		entDB:        entDB,
		service:      service,
		logger:       log,
		clock:        func() time.Time { return time.Now().UTC() },
		eventMaxRows: eventMaxRows,
	}
}

// Start launches the sweep goroutine. It performs an initial sweep
// immediately (catches missed sweeps after registry downtime) and then
// runs every sweepInterval until the goroutine's context is cancelled or
// Stop is called.
//
// If cfg.Retention is zero or negative the job is treated as disabled
// and Start is a no-op.
func (s *SweepJob) Start(ctx context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.cfg.Retention <= 0 {
		if s.logger != nil {
			s.logger.Info("🧹 Registry sweep job disabled (MCP_MESH_RETENTION=0)")
		}
		return
	}
	if s.running {
		if s.logger != nil {
			s.logger.Warning("Sweep job already running")
		}
		return
	}

	jobCtx, cancel := context.WithCancel(ctx)
	s.cancel = cancel
	s.running = true
	s.wg.Add(1)

	go func() {
		defer s.wg.Done()
		if s.logger != nil {
			s.logger.Info("🧹 Starting registry sweep job (retention=%s)", s.cfg.Retention)
		}

		// Run once at startup to catch missed sweeps after downtime.
		s.tick(jobCtx)

		ticker := time.NewTicker(sweepInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				s.tick(jobCtx)
			case <-jobCtx.Done():
				if s.logger != nil {
					s.logger.Info("🛑 Registry sweep job stopped")
				}
				return
			}
		}
	}()
}

// Stop cancels the sweep goroutine and waits for the current tick to finish.
// Safe to call even if Start was never invoked or the job is already stopped.
func (s *SweepJob) Stop() {
	s.mu.Lock()
	if !s.running {
		s.mu.Unlock()
		return
	}
	s.running = false
	cancel := s.cancel
	s.mu.Unlock()

	if cancel != nil {
		cancel()
	}
	s.wg.Wait()
}

// tick runs a single sweep iteration with logging. Errors are logged but
// not surfaced; the next tick will retry.
func (s *SweepJob) tick(ctx context.Context) {
	start := s.clock()
	agentsPurged, eventsPurged, err := s.runOnce(ctx)
	took := time.Since(start)

	if err != nil {
		if s.logger != nil {
			s.logger.Error("sweep: failed (took %s): %v", took, err)
		}
		return
	}

	if s.logger != nil {
		if agentsPurged > 0 || eventsPurged > 0 {
			s.logger.Info("sweep: purged %d agents, %d events (took %s)", agentsPurged, eventsPurged, took)
		} else {
			s.logger.Debug("sweep: nothing to purge (took %s)", took)
		}
	}
}

// runOnce performs a single sweep iteration and returns the number of
// agents and events purged. Exported (lower-cased but callable from
// tests in the same package) for unit tests; production callers should
// use Start.
func (s *SweepJob) runOnce(ctx context.Context) (agentsPurged, eventsPurged int, err error) {
	now := s.clock()

	if s.cfg.Retention > 0 {
		n, err := s.purgeStaleAgents(ctx, now)
		if err != nil {
			return 0, 0, fmt.Errorf("purge stale agents: %w", err)
		}
		agentsPurged = n
	}

	n, err := s.enforceEventCap(ctx)
	if err != nil {
		return agentsPurged, 0, fmt.Errorf("enforce event cap: %w", err)
	}
	eventsPurged = n

	return agentsPurged, eventsPurged, nil
}

// purgeStaleAgents deletes agents in unhealthy/unknown status that have
// not heartbeated within Retention.
//
// For each candidate agent we first flip provider-side resolution rows
// (dependency_resolution, llm_tool_resolution, llm_provider_resolution)
// to status=unavailable so consumers don't see stale "available"
// pointers, then delete the agent. The schema-level OnDelete: Cascade
// removes capabilities, events, and consumer-side rows automatically;
// the provider-side rows have SetNull, which is why we explicitly mark
// them unavailable beforehand.
//
// The orphan-fix and delete are wrapped in a single transaction. Inside
// the transaction we re-query the agent against the same staleness
// predicate to detect a concurrent heartbeat that would have revived
// it; if the predicate no longer matches we skip the row entirely (the
// transaction commits as a no-op).
func (s *SweepJob) purgeStaleAgents(ctx context.Context, now time.Time) (int, error) {
	threshold := now.Add(-s.cfg.Retention)

	candidates, err := s.entDB.Client.Agent.
		Query().
		Where(
			agent.StatusIn(agent.StatusUnhealthy, agent.StatusUnknown),
			agent.UpdatedAtLT(threshold),
		).
		All(ctx)
	if err != nil {
		return 0, fmt.Errorf("query stale agents: %w", err)
	}

	if len(candidates) == 0 {
		return 0, nil
	}

	var purged int
	for _, a := range candidates {
		didPurge, err := s.purgeOneAgent(ctx, a, threshold)
		if err != nil {
			if s.logger != nil {
				s.logger.Error("sweep: failed to purge agent %s: %v", a.ID, err)
			}
			continue
		}
		if didPurge {
			purged++
		}
	}
	return purged, nil
}

// purgeOneAgent runs the orphan-fix + delete pair for a single agent
// inside a transaction. Returns (true, nil) when the agent was actually
// deleted, (false, nil) when a concurrent heartbeat revived it (race
// lost; no-op), or (_, err) on failure.
//
// The race-safety strategy: re-query the agent inside the tx using the
// same staleness predicate as the candidate scan. If the agent no longer
// matches (heartbeat arrived between scan and tx open), we abort early
// and skip orphan-fix entirely. The re-query inside the tx, plus the
// transaction's isolation, prevents the unconditional DeleteOneID below
// from killing a freshly-healthy agent.
func (s *SweepJob) purgeOneAgent(ctx context.Context, a *ent.Agent, threshold time.Time) (bool, error) {
	var deleted bool

	err := s.entDB.Transaction(ctx, func(tx *ent.Tx) error {
		// Re-check staleness inside the tx. If the agent heartbeated
		// between the candidate scan and this tx, it will no longer
		// match the predicate and we bail out without touching deps.
		match, err := tx.Agent.Query().
			Where(
				agent.IDEQ(a.ID),
				agent.StatusIn(agent.StatusUnhealthy, agent.StatusUnknown),
				agent.UpdatedAtLT(threshold),
			).
			Count(ctx)
		if err != nil {
			return fmt.Errorf("re-check agent %s: %w", a.ID, err)
		}
		if match == 0 {
			// Race lost: agent revived. No-op, commit empty tx.
			if s.logger != nil {
				s.logger.Debug("sweep: skipped purge of agent %s (no longer stale)", a.ID)
			}
			return nil
		}

		// Orphan-fix: flip all three resolution tables before deleting.
		// The FK is SetNull (not Cascade), so without this the rows
		// would be left dangling with status=available and a NULL
		// provider_agent_id after the delete.
		if _, err := tx.DependencyResolution.Update().
			Where(dependencyresolution.ProviderAgentIDEQ(a.ID)).
			SetStatus(dependencyresolution.StatusUnavailable).
			ClearResolvedAt().
			Save(ctx); err != nil {
			return fmt.Errorf("flip dep resolutions for %s: %w", a.ID, err)
		}
		if _, err := tx.LLMToolResolution.Update().
			Where(llmtoolresolution.ProviderAgentIDEQ(a.ID)).
			SetStatus(llmtoolresolution.StatusUnavailable).
			ClearResolvedAt().
			Save(ctx); err != nil {
			return fmt.Errorf("flip llm tool resolutions for %s: %w", a.ID, err)
		}
		if _, err := tx.LLMProviderResolution.Update().
			Where(llmproviderresolution.ProviderAgentIDEQ(a.ID)).
			SetStatus(llmproviderresolution.StatusUnavailable).
			ClearResolvedAt().
			Save(ctx); err != nil {
			return fmt.Errorf("flip llm provider resolutions for %s: %w", a.ID, err)
		}

		if err := tx.Agent.DeleteOneID(a.ID).Exec(ctx); err != nil {
			return fmt.Errorf("delete agent %s: %w", a.ID, err)
		}

		deleted = true
		return nil
	})
	if err != nil {
		return false, err
	}

	if deleted && s.logger != nil {
		s.logger.Debug("sweep: purged agent %s (status=%s, last updated %s)", a.ID, a.Status, a.UpdatedAt.UTC().Format(time.RFC3339))
	}
	return deleted, nil
}

// enforceEventCap deletes the oldest events when the table exceeds the
// internal hard cap (s.eventMaxRows, defaulting to the package constant).
// Events are governed solely by row count, not age.
func (s *SweepJob) enforceEventCap(ctx context.Context) (int, error) {
	count, err := s.entDB.Client.RegistryEvent.Query().Count(ctx)
	if err != nil {
		return 0, fmt.Errorf("count events: %w", err)
	}
	if count <= s.eventMaxRows {
		return 0, nil
	}

	excess := count - s.eventMaxRows
	oldest, err := s.entDB.Client.RegistryEvent.
		Query().
		Order(ent.Asc(registryevent.FieldTimestamp)).
		Limit(excess).
		IDs(ctx)
	if err != nil {
		return 0, fmt.Errorf("select oldest events: %w", err)
	}
	if len(oldest) == 0 {
		return 0, nil
	}

	n, err := s.entDB.Client.RegistryEvent.
		Delete().
		Where(registryevent.IDIn(oldest...)).
		Exec(ctx)
	if err != nil {
		return 0, fmt.Errorf("delete excess events: %w", err)
	}
	return n, nil
}

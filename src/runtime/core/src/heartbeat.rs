//! Heartbeat state machine for MCP Mesh agents.
//!
//! Implements the dual-heartbeat system:
//! - Fast HEAD requests every ~5 seconds (lightweight check)
//! - Full POST heartbeat only when topology changes detected

use std::time::{Duration, Instant};
use tracing::{debug, info, trace, warn};
use uuid::Uuid;

use crate::events::HealthStatus;
use crate::registry::{FastHeartbeatResponse, FastHeartbeatStatus};

/// State of the heartbeat state machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HeartbeatState {
    /// Not yet registered with registry
    Unregistered,
    /// Registered and healthy
    Healthy,
    /// Registered but degraded health
    Degraded,
    /// Lost connection to registry, attempting to reconnect
    Reconnecting,
    /// Shutting down
    ShuttingDown,
}

impl Default for HeartbeatState {
    fn default() -> Self {
        Self::Unregistered
    }
}

/// Action to take based on heartbeat state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HeartbeatAction {
    /// Send full heartbeat/registration (POST)
    SendFull,
    /// Send fast heartbeat check (HEAD)
    SendFast,
    /// Wait for specified duration before next action
    Wait(Duration),
    /// Retry after backoff
    Retry { attempt: u32, backoff: Duration },
    /// No action needed (shutdown)
    None,
}

/// Configuration for heartbeat behavior.
#[derive(Debug, Clone)]
pub struct HeartbeatConfig {
    /// Interval between heartbeats (seconds)
    pub interval: Duration,
    /// Maximum retry attempts before giving up
    pub max_retries: u32,
    /// Base backoff duration for retries
    pub base_backoff: Duration,
    /// Maximum backoff duration
    pub max_backoff: Duration,
    /// Number of missed heartbeats before considering connection lost
    pub missed_threshold: u32,
}

impl Default for HeartbeatConfig {
    fn default() -> Self {
        Self {
            interval: Duration::from_secs(5),
            max_retries: 5,
            base_backoff: Duration::from_secs(1),
            max_backoff: Duration::from_secs(30),
            missed_threshold: 4,
        }
    }
}

/// Heartbeat state machine for managing agent registration and heartbeats.
pub struct HeartbeatStateMachine {
    /// Current state
    state: HeartbeatState,
    /// Configuration
    config: HeartbeatConfig,
    /// Current health status
    health_status: HealthStatus,
    /// Last successful heartbeat time
    last_heartbeat: Option<Instant>,
    /// Number of consecutive failures
    consecutive_failures: u32,
    /// Current retry attempt
    retry_attempt: u32,
    /// Whether initial registration was successful
    registered: bool,
    /// Count of heartbeats sent
    heartbeat_count: u64,
}

impl HeartbeatStateMachine {
    /// Create a new heartbeat state machine.
    pub fn new(config: HeartbeatConfig) -> Self {
        Self {
            state: HeartbeatState::Unregistered,
            config,
            health_status: HealthStatus::Healthy,
            last_heartbeat: None,
            consecutive_failures: 0,
            retry_attempt: 0,
            registered: false,
            heartbeat_count: 0,
        }
    }

    /// Get the current state.
    pub fn state(&self) -> HeartbeatState {
        self.state
    }

    /// Get the current health status.
    pub fn health_status(&self) -> HealthStatus {
        self.health_status
    }

    /// Set the health status.
    pub fn set_health_status(&mut self, status: HealthStatus) {
        if self.health_status != status {
            info!("Health status changed: {:?} -> {:?}", self.health_status, status);
            self.health_status = status;
        }
    }

    /// Get the heartbeat count.
    pub fn heartbeat_count(&self) -> u64 {
        self.heartbeat_count
    }

    /// Determine the next action to take.
    pub fn next_action(&self) -> HeartbeatAction {
        match self.state {
            HeartbeatState::Unregistered => HeartbeatAction::SendFull,
            HeartbeatState::Healthy | HeartbeatState::Degraded => {
                if self.should_send_heartbeat() {
                    HeartbeatAction::SendFast
                } else {
                    HeartbeatAction::Wait(self.time_until_next_heartbeat())
                }
            }
            HeartbeatState::Reconnecting => {
                let backoff = self.calculate_backoff();
                HeartbeatAction::Retry {
                    attempt: self.retry_attempt,
                    backoff,
                }
            }
            HeartbeatState::ShuttingDown => HeartbeatAction::None,
        }
    }

    /// Process the result of a fast heartbeat check.
    ///
    /// Accepts a [`FastHeartbeatResponse`] so callers can plumb the
    /// `pending_jobs` hint up to the runtime alongside the status. The
    /// state machine itself only consumes the status; the pending-jobs
    /// signal is the runtime's responsibility (see `AgentRuntime`).
    pub fn on_fast_heartbeat_result(
        &mut self,
        response: FastHeartbeatResponse,
    ) -> HeartbeatAction {
        let status = response.status;
        trace!(
            "Fast heartbeat result: {:?} pending_jobs={:?}",
            status, response.pending_jobs
        );

        match status {
            FastHeartbeatStatus::NoChanges => {
                // Everything is fine, just update timestamp
                self.last_heartbeat = Some(Instant::now());
                self.consecutive_failures = 0;
                self.heartbeat_count += 1;
                HeartbeatAction::Wait(self.config.interval)
            }
            FastHeartbeatStatus::TopologyChanged => {
                // Need to send full heartbeat to get updated topology
                debug!("Topology changed, sending full heartbeat");
                HeartbeatAction::SendFull
            }
            FastHeartbeatStatus::AgentUnknown => {
                // Registry doesn't know us, need to re-register
                warn!("Agent unknown to registry, re-registering");
                self.registered = false;
                self.state = HeartbeatState::Unregistered;
                HeartbeatAction::SendFull
            }
            FastHeartbeatStatus::RegistryError | FastHeartbeatStatus::NetworkError => {
                // Error, but don't panic - just wait and retry
                self.consecutive_failures += 1;
                warn!(
                    "Fast heartbeat error ({:?}), failure count: {}",
                    status, self.consecutive_failures
                );

                if self.consecutive_failures >= self.config.missed_threshold {
                    self.state = HeartbeatState::Reconnecting;
                    self.retry_attempt = 0;
                }

                HeartbeatAction::Wait(self.config.interval)
            }
        }
    }

    /// Process the result of a full heartbeat.
    pub fn on_full_heartbeat_success(&mut self) {
        info!("Full heartbeat successful");
        self.last_heartbeat = Some(Instant::now());
        self.consecutive_failures = 0;
        self.retry_attempt = 0;
        self.registered = true;
        self.heartbeat_count += 1;

        self.state = match self.health_status {
            HealthStatus::Healthy => HeartbeatState::Healthy,
            HealthStatus::Degraded => HeartbeatState::Degraded,
            HealthStatus::Unhealthy => HeartbeatState::Degraded,
        };
    }

    /// Process a full heartbeat failure.
    pub fn on_full_heartbeat_failure(&mut self, error: &str) {
        warn!("Full heartbeat failed: {}", error);
        self.consecutive_failures += 1;
        self.retry_attempt += 1;

        if self.consecutive_failures >= self.config.missed_threshold {
            self.state = HeartbeatState::Reconnecting;
        }
    }

    /// Request shutdown.
    pub fn shutdown(&mut self) {
        info!("Heartbeat shutdown requested");
        self.state = HeartbeatState::ShuttingDown;
    }

    /// Check if shutdown was requested.
    pub fn is_shutting_down(&self) -> bool {
        self.state == HeartbeatState::ShuttingDown
    }

    /// Check if we're registered.
    pub fn is_registered(&self) -> bool {
        self.registered
    }

    // Private helpers

    fn should_send_heartbeat(&self) -> bool {
        match self.last_heartbeat {
            Some(last) => last.elapsed() >= self.config.interval,
            None => true,
        }
    }

    fn time_until_next_heartbeat(&self) -> Duration {
        match self.last_heartbeat {
            Some(last) => {
                let elapsed = last.elapsed();
                if elapsed >= self.config.interval {
                    Duration::ZERO
                } else {
                    self.config.interval - elapsed
                }
            }
            None => Duration::ZERO,
        }
    }

    fn calculate_backoff(&self) -> Duration {
        // Exponential backoff with equal jitter.
        let base = self.config.base_backoff.as_millis() as u64;
        let factor = 2u64.saturating_pow(self.retry_attempt);
        let backoff_ms = base.saturating_mul(factor);
        let max_ms = self.config.max_backoff.as_millis() as u64;

        let capped = backoff_ms.min(max_ms);
        let half = capped / 2;
        // Equal jitter: half deterministic + up to half random (decorrelates
        // reconnects so agents don't retry in lockstep on registry recovery).
        let rand_part = if half > 0 {
            let bytes = Uuid::new_v4().into_bytes();
            let r = u64::from_le_bytes(bytes[0..8].try_into().unwrap());
            r % (half + 1)
        } else {
            0
        };
        Duration::from_millis(half + rand_part)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_initial_state() {
        let sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        assert_eq!(sm.state(), HeartbeatState::Unregistered);
        assert!(!sm.is_registered());
    }

    #[test]
    fn test_unregistered_action() {
        let sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        assert_eq!(sm.next_action(), HeartbeatAction::SendFull);
    }

    #[test]
    fn test_registration_success() {
        let mut sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        sm.on_full_heartbeat_success();

        assert!(sm.is_registered());
        assert_eq!(sm.state(), HeartbeatState::Healthy);
    }

    /// Helper for tests: build a `FastHeartbeatResponse` with no pending-jobs.
    fn fhb(status: FastHeartbeatStatus) -> FastHeartbeatResponse {
        FastHeartbeatResponse {
            status,
            pending_jobs: None,
        }
    }

    #[test]
    fn test_fast_heartbeat_no_changes() {
        let mut sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        sm.on_full_heartbeat_success();

        let action = sm.on_fast_heartbeat_result(fhb(FastHeartbeatStatus::NoChanges));
        assert!(matches!(action, HeartbeatAction::Wait(_)));
    }

    #[test]
    fn test_fast_heartbeat_topology_changed() {
        let mut sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        sm.on_full_heartbeat_success();

        let action = sm.on_fast_heartbeat_result(fhb(FastHeartbeatStatus::TopologyChanged));
        assert_eq!(action, HeartbeatAction::SendFull);
    }

    #[test]
    fn test_agent_unknown_triggers_reregister() {
        let mut sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        sm.on_full_heartbeat_success();
        assert!(sm.is_registered());

        let action = sm.on_fast_heartbeat_result(fhb(FastHeartbeatStatus::AgentUnknown));
        assert_eq!(action, HeartbeatAction::SendFull);
        assert!(!sm.is_registered());
        assert_eq!(sm.state(), HeartbeatState::Unregistered);
    }

    #[test]
    fn test_consecutive_failures_trigger_reconnect() {
        let config = HeartbeatConfig {
            missed_threshold: 3,
            ..Default::default()
        };
        let mut sm = HeartbeatStateMachine::new(config);
        sm.on_full_heartbeat_success();

        // Three failures should trigger reconnecting state
        sm.on_fast_heartbeat_result(fhb(FastHeartbeatStatus::NetworkError));
        assert_eq!(sm.state(), HeartbeatState::Healthy);

        sm.on_fast_heartbeat_result(fhb(FastHeartbeatStatus::NetworkError));
        assert_eq!(sm.state(), HeartbeatState::Healthy);

        sm.on_fast_heartbeat_result(fhb(FastHeartbeatStatus::NetworkError));
        assert_eq!(sm.state(), HeartbeatState::Reconnecting);
    }

    #[test]
    fn test_pending_jobs_carries_through_response_struct() {
        // The state machine ignores pending_jobs (runtime owns it), but the
        // response struct should preserve the value so the runtime can read it
        // alongside the action.
        let resp = FastHeartbeatResponse {
            status: FastHeartbeatStatus::NoChanges,
            pending_jobs: Some(7),
        };
        assert_eq!(resp.pending_jobs, Some(7));

        let mut sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        sm.on_full_heartbeat_success();
        let _ = sm.on_fast_heartbeat_result(resp);
        // No assertion on the action — just verify the call shape compiles
        // and doesn't disturb the existing semantics.
    }

    #[test]
    fn test_backoff_calculation() {
        let mut sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        sm.retry_attempt = 0;
        let backoff0 = sm.calculate_backoff();

        sm.retry_attempt = 1;
        let backoff1 = sm.calculate_backoff();

        sm.retry_attempt = 2;
        let backoff2 = sm.calculate_backoff();

        // Should be (non-strictly) increasing — equal jitter floors each
        // attempt at capped/2, which equals the previous attempt's ceiling, so
        // adjacent attempts can tie but never invert.
        assert!(backoff1 >= backoff0);
        assert!(backoff2 >= backoff1);
    }

    #[test]
    fn test_backoff_jitter() {
        let config = HeartbeatConfig::default();
        let max_ms = config.max_backoff.as_millis() as u64;
        let mut sm = HeartbeatStateMachine::new(config);
        sm.retry_attempt = 2;

        // capped = base(1000) * 2^2 = 4000, floored at capped/2 = 2000.
        let capped = 4000u64.min(max_ms);
        let floor = capped / 2;

        let mut values = std::collections::HashSet::new();
        for _ in 0..20 {
            let ms = sm.calculate_backoff().as_millis() as u64;
            assert!(ms <= max_ms, "{} exceeds max_backoff {}", ms, max_ms);
            assert!(ms <= capped, "{} exceeds capped {}", ms, capped);
            assert!(ms >= floor, "{} below floor {}", ms, floor);
            values.insert(ms);
        }

        // Jitter must produce variation across calls.
        assert!(
            values.len() >= 2,
            "expected jittered backoff to vary, got {:?}",
            values
        );
    }

    #[test]
    fn test_shutdown() {
        let mut sm = HeartbeatStateMachine::new(HeartbeatConfig::default());
        sm.shutdown();

        assert!(sm.is_shutting_down());
        assert_eq!(sm.next_action(), HeartbeatAction::None);
    }
}

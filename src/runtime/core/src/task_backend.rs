//! `TaskBackend` trait — pluggable substrate for the MeshJob coordination
//! layer. Phase 1 ships a single implementation,
//! [`RegistryHttpBackend`], which speaks to the Go registry's `/jobs/*`
//! endpoints. Future implementations (Redis, FastMCP-Docket, etc.) plug in
//! behind the same trait without changes to the agent-facing API.
//!
//! Wire shapes mirror `api/mcp-mesh-registry.openapi.yaml` schemas
//! (`Job`, `CreateJobRequest`, `JobDelta`, …) field-for-field. Field
//! renames between snake_case JSON and Rust idiom go through `serde`.
//!
//! See `MESHJOB_DESIGN.org` → "Architecture / Layer map" for context.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tracing::{debug, warn};

// =============================================================================
// Wire types — mirror OpenAPI schemas
// =============================================================================

/// Job lifecycle status. Terminal: `completed`, `failed`, `cancelled`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Working,
    InputRequired,
    Completed,
    Failed,
    Cancelled,
}

impl JobStatus {
    /// Whether this status is terminal (no further transitions allowed).
    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Completed | Self::Failed | Self::Cancelled)
    }
}

/// Producer-side request to register a new job (`POST /jobs`).
#[derive(Debug, Clone, Serialize)]
pub struct CreateJobRequest {
    pub capability: String,
    pub submitted_payload: serde_json::Value,
    pub submitted_by: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_retries: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_duration: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_deadline: Option<i64>, // Unix epoch (nullable column)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub owner_instance_id: Option<String>,
}

/// Response from `POST /jobs`.
#[derive(Debug, Clone, Deserialize)]
pub struct CreateJobResponse {
    pub id: String,
    pub status: JobStatus,
    #[serde(default)]
    pub owner_instance_id: Option<String>,
}

/// Single delta in a job batch (`JobDelta` schema).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobDelta {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<JobStatus>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub progress: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub progress_message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl JobDelta {
    /// Construct a progress-only delta (non-terminal).
    pub fn progress(id: impl Into<String>, progress: f32, message: Option<String>) -> Self {
        Self {
            id: id.into(),
            status: None,
            progress: Some(progress),
            progress_message: message,
            result: None,
            error: None,
        }
    }

    /// Construct a terminal `completed` delta with a result payload.
    pub fn completed(id: impl Into<String>, result: serde_json::Value) -> Self {
        Self {
            id: id.into(),
            status: Some(JobStatus::Completed),
            progress: Some(1.0),
            progress_message: None,
            result: Some(result),
            error: None,
        }
    }

    /// Construct a terminal `failed` delta with an error reason.
    pub fn failed(id: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            status: Some(JobStatus::Failed),
            progress: None,
            progress_message: None,
            result: None,
            error: Some(error.into()),
        }
    }

    /// Whether this delta would transition the job to a terminal state.
    pub fn is_terminal(&self) -> bool {
        self.status.map(|s| s.is_terminal()).unwrap_or(false)
    }
}

/// Request body for `POST /jobs/batch`.
#[derive(Debug, Clone, Serialize)]
pub struct JobBatchRequest {
    pub instance_id: String,
    pub deltas: Vec<JobDelta>,
}

/// Per-batch outcome (`JobBatchResponse` schema).
#[derive(Debug, Clone, Deserialize)]
pub struct JobBatchResponse {
    pub accepted: u32,
    #[serde(default)]
    pub rejected: Vec<RejectedDelta>,
}

/// One entry in `JobBatchResponse.rejected`.
#[derive(Debug, Clone, Deserialize)]
pub struct RejectedDelta {
    pub id: String,
    pub reason: String,
}

/// Request body for `POST /jobs/claim`.
#[derive(Debug, Clone, Serialize)]
pub struct ClaimJobsRequest {
    pub capability: String,
    pub instance_id: String,
}

/// One claimed job in `ClaimJobsResponse.claimed[]`.
#[derive(Debug, Clone, Deserialize)]
pub struct ClaimedJob {
    pub id: String,
    pub submitted_payload: serde_json::Value,
    pub attempt_count: u32,
    #[serde(default)]
    pub lease_expires_at: Option<i64>,
    #[serde(default)]
    pub max_duration: Option<u32>,
}

/// Response from `POST /jobs/claim`.
#[derive(Debug, Clone, Deserialize)]
pub struct ClaimJobsResponse {
    pub claimed: Vec<ClaimedJob>,
}

/// Cancel request body (`POST /jobs/{id}/cancel`).
#[derive(Debug, Clone, Serialize, Default)]
pub struct CancelJobRequest {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

/// Response from `POST /jobs/{id}/cancel`.
#[derive(Debug, Clone, Deserialize)]
pub struct CancelJobResponse {
    pub status: JobStatus,
    #[serde(default)]
    pub forwarded_to_instance_id: Option<String>,
}

/// Release request body (`POST /jobs/{id}/release`). Producer voluntarily
/// drops its lease so a peer replica can re-claim and retry — used by the
/// SDK when a handler raised a `retry_on`-matched exception.
#[derive(Debug, Clone, Serialize)]
pub struct ReleaseJobRequest {
    pub instance_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

/// Response from `POST /jobs/{id}/release`. The `status` field reflects the
/// post-release state — either `working` (released for retry; a peer can
/// re-claim within ~5s via the HEAD-heartbeat path) or `failed` (the
/// existing `attempt_count` from the claim-time increment was already past
/// `max_retries`, so the registry marked the row exhausted on release).
/// Release itself does NOT increment `attempt_count` — that happens only at
/// claim time, so by the time `POST /jobs/{id}/release` runs, the field
/// already reflects "this attempt".
#[derive(Debug, Clone, Deserialize)]
pub struct ReleaseJobResponse {
    pub status: JobStatus,
    pub attempt_count: u32,
}

/// Full job record (`Job` schema).
#[derive(Debug, Clone, Deserialize)]
pub struct Job {
    pub id: String,
    pub capability: String,
    #[serde(default)]
    pub owner_instance_id: Option<String>,
    pub status: JobStatus,
    #[serde(default)]
    pub progress: Option<f32>,
    #[serde(default)]
    pub progress_message: Option<String>,
    #[serde(default)]
    pub result: Option<serde_json::Value>,
    #[serde(default)]
    pub error: Option<String>,
    pub submitted_payload: serde_json::Value,
    pub attempt_count: u32,
    pub max_retries: u32,
    #[serde(default)]
    pub max_duration: Option<u32>,
    #[serde(default)]
    pub total_deadline: Option<i64>,
    #[serde(default)]
    pub lease_expires_at: Option<i64>,
    #[serde(default)]
    pub last_heartbeat_at: Option<i64>,
    pub submitted_at: i64,
    pub submitted_by: String,
}

// =============================================================================
// Errors
// =============================================================================

/// Errors returned by [`TaskBackend`] implementations.
#[derive(Debug, Error)]
pub enum BackendError {
    /// Job ID does not exist (HTTP 404).
    #[error("job not found: {0}")]
    NotFound(String),

    /// State transition rejected (HTTP 409, e.g. cancel of terminal job).
    #[error("conflict: {0}")]
    Conflict(String),

    /// Registry returned 503 (or backend infrastructure unavailable).
    #[error("backend unavailable: {0}")]
    BackendUnavailable(String),

    /// Network / transport error.
    #[error("network error: {0}")]
    Network(#[from] reqwest::Error),

    /// JSON encode/decode failure.
    #[error("serialization error: {0}")]
    Serialize(#[from] serde_json::Error),

    /// Server-side HTTP error (5xx, other than 503 → BackendUnavailable).
    /// Treated as transient — registry may have rolled, restarted, or be
    /// momentarily overloaded.
    #[error("server error (HTTP {0}): {1}")]
    Server(u16, String),

    /// Catch-all (HTTP 4xx not otherwise classified, etc.).
    #[error("backend error: {0}")]
    Other(String),
}

impl BackendError {
    /// Whether this error represents a transient condition that callers
    /// (e.g. the consumer-side polling loop in [`crate::jobs::JobProxy::wait`])
    /// should ride through with backoff rather than surfacing immediately.
    ///
    /// Transient = anything that can plausibly self-heal within a k8s
    /// rolling-restart window: network/transport errors, 503 backend
    /// unavailable, and other 5xx server errors. NOT transient: 404
    /// (job genuinely doesn't exist), 409 (state conflict), 4xx (client
    /// bug), serialisation failures (wire-format mismatch).
    pub fn is_transient(&self) -> bool {
        matches!(
            self,
            BackendError::Network(_)
                | BackendError::BackendUnavailable(_)
                | BackendError::Server(_, _)
        )
    }
}

// =============================================================================
// Trait
// =============================================================================

/// Coordination substrate for job state. Phase 1 ships
/// [`RegistryHttpBackend`]; future Redis / FastMCP-Docket impls plug in
/// behind the same trait.
#[async_trait]
pub trait TaskBackend: Send + Sync {
    /// Producer-side: submit a job (`POST /jobs`). When `owner_instance_id`
    /// is set in the request, registry pins the job to that replica
    /// (push mode); otherwise the job starts unclaimed (pull mode).
    async fn create_job(
        &self,
        req: CreateJobRequest,
    ) -> Result<CreateJobResponse, BackendError>;

    /// Producer-side: push a coalesced delta batch
    /// (`POST /jobs/batch`).
    async fn submit_batch(
        &self,
        instance_id: &str,
        deltas: Vec<JobDelta>,
    ) -> Result<JobBatchResponse, BackendError>;

    /// Producer-side: atomically claim one pending job for `capability`
    /// (`POST /jobs/claim`). Empty `claimed` array means no work was
    /// available — that is success, not error.
    async fn claim_next(
        &self,
        capability: &str,
        instance_id: &str,
    ) -> Result<Option<ClaimedJob>, BackendError>;

    /// Anyone-side: read the latest persisted job state
    /// (`GET /jobs/{id}`).
    async fn get_job(&self, job_id: &str) -> Result<Job, BackendError>;

    /// Anyone-side: cancel an in-flight job
    /// (`POST /jobs/{id}/cancel`). Registry forwards the cancel signal
    /// to the owner replica when one is alive.
    async fn cancel_job(
        &self,
        job_id: &str,
        reason: Option<String>,
    ) -> Result<CancelJobResponse, BackendError>;

    /// Producer-side: voluntarily release the lease on a `working` job
    /// (`POST /jobs/{id}/release`). Used when the handler raised an
    /// exception matched by the tool's `retry_on` whitelist — instead of
    /// `fail()` (terminal), release lets a peer replica re-claim within
    /// ~5s. If `attempt_count` exceeds `max_retries` after the registry's
    /// increment, the response carries `status=failed` (terminal,
    /// exhausted).
    async fn release_lease(
        &self,
        job_id: &str,
        instance_id: &str,
        reason: Option<String>,
    ) -> Result<ReleaseJobResponse, BackendError>;
}

// =============================================================================
// RegistryHttpBackend — Phase 1 implementation
// =============================================================================

/// `TaskBackend` impl that speaks the registry's `/jobs/*` HTTP API.
///
/// Uses a single shared `reqwest::Client` (created at construction time).
/// TLS configuration is handled by the caller — pass in a pre-built client
/// when mTLS is required (mirrors how `RegistryClient` is wired in
/// `runtime.rs`).
pub struct RegistryHttpBackend {
    client: Client,
    base_url: String,
}

impl RegistryHttpBackend {
    /// Construct a new backend with default HTTP client. For mTLS use
    /// [`Self::with_client`].
    pub fn new(registry_url: &str) -> Result<Self, BackendError> {
        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .connect_timeout(Duration::from_secs(10))
            .pool_max_idle_per_host(20)
            .pool_idle_timeout(Duration::from_secs(90))
            .build()
            .map_err(BackendError::Network)?;
        Ok(Self::with_client(registry_url, client))
    }

    /// Construct with a pre-built client (use when caller needs to plug in
    /// mTLS identity, custom CA, etc.).
    pub fn with_client(registry_url: &str, client: Client) -> Self {
        let base_url = registry_url.trim_end_matches('/').to_string();
        Self { client, base_url }
    }

    /// Wrap `Self` in an `Arc<dyn TaskBackend>` for use with the agent-facing
    /// job APIs (which take `Arc<dyn TaskBackend>` for substrate hot-swap).
    pub fn into_arc(self) -> Arc<dyn TaskBackend> {
        Arc::new(self)
    }

    /// Internal: classify a non-2xx HTTP response into a `BackendError`.
    async fn classify_error(resp: reqwest::Response) -> BackendError {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        match status.as_u16() {
            404 => BackendError::NotFound(body),
            409 => BackendError::Conflict(body),
            503 => BackendError::BackendUnavailable(body),
            // Other 5xx → transient server error (k8s rolling restart, etc.)
            code if (500..600).contains(&code) => BackendError::Server(code, body),
            code => BackendError::Other(format!("HTTP {}: {}", code, body)),
        }
    }
}

#[async_trait]
impl TaskBackend for RegistryHttpBackend {
    async fn create_job(
        &self,
        req: CreateJobRequest,
    ) -> Result<CreateJobResponse, BackendError> {
        let url = format!("{}/jobs", self.base_url);
        debug!("POST {} (capability={})", url, req.capability);
        let resp = self.client.post(&url).json(&req).send().await?;
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        Ok(resp.json::<CreateJobResponse>().await?)
    }

    async fn submit_batch(
        &self,
        instance_id: &str,
        deltas: Vec<JobDelta>,
    ) -> Result<JobBatchResponse, BackendError> {
        let url = format!("{}/jobs/batch", self.base_url);
        let body = JobBatchRequest {
            instance_id: instance_id.to_string(),
            deltas,
        };
        debug!(
            "POST {} (instance_id={}, deltas={})",
            url,
            instance_id,
            body.deltas.len()
        );
        let resp = self.client.post(&url).json(&body).send().await?;
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        let parsed: JobBatchResponse = resp.json().await?;
        if !parsed.rejected.is_empty() {
            warn!(
                "Job batch had {} rejected deltas (accepted={})",
                parsed.rejected.len(),
                parsed.accepted
            );
        }
        Ok(parsed)
    }

    async fn claim_next(
        &self,
        capability: &str,
        instance_id: &str,
    ) -> Result<Option<ClaimedJob>, BackendError> {
        let url = format!("{}/jobs/claim", self.base_url);
        let body = ClaimJobsRequest {
            capability: capability.to_string(),
            instance_id: instance_id.to_string(),
        };
        debug!("POST {} (capability={})", url, capability);
        let resp = self.client.post(&url).json(&body).send().await?;
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        let parsed: ClaimJobsResponse = resp.json().await?;
        Ok(parsed.claimed.into_iter().next())
    }

    async fn get_job(&self, job_id: &str) -> Result<Job, BackendError> {
        let url = format!("{}/jobs/{}", self.base_url, job_id);
        let resp = self.client.get(&url).send().await?;
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        Ok(resp.json::<Job>().await?)
    }

    async fn cancel_job(
        &self,
        job_id: &str,
        reason: Option<String>,
    ) -> Result<CancelJobResponse, BackendError> {
        let url = format!("{}/jobs/{}/cancel", self.base_url, job_id);
        let body = CancelJobRequest { reason };
        let resp = self.client.post(&url).json(&body).send().await?;
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        Ok(resp.json::<CancelJobResponse>().await?)
    }

    async fn release_lease(
        &self,
        job_id: &str,
        instance_id: &str,
        reason: Option<String>,
    ) -> Result<ReleaseJobResponse, BackendError> {
        let url = format!("{}/jobs/{}/release", self.base_url, job_id);
        let body = ReleaseJobRequest {
            instance_id: instance_id.to_string(),
            reason,
        };
        debug!(
            "POST {} (instance_id={}, has_reason={})",
            url,
            instance_id,
            body.reason.is_some()
        );
        let resp = self.client.post(&url).json(&body).send().await?;
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        Ok(resp.json::<ReleaseJobResponse>().await?)
    }
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_status_terminal_classification() {
        assert!(JobStatus::Completed.is_terminal());
        assert!(JobStatus::Failed.is_terminal());
        assert!(JobStatus::Cancelled.is_terminal());
        assert!(!JobStatus::Working.is_terminal());
        assert!(!JobStatus::InputRequired.is_terminal());
    }

    #[test]
    fn job_status_serializes_snake_case() {
        let s = serde_json::to_string(&JobStatus::InputRequired).unwrap();
        assert_eq!(s, "\"input_required\"");
        let parsed: JobStatus = serde_json::from_str("\"completed\"").unwrap();
        assert_eq!(parsed, JobStatus::Completed);
    }

    #[test]
    fn job_delta_progress_constructor() {
        let d = JobDelta::progress("job-1", 0.5, Some("halfway".into()));
        assert_eq!(d.id, "job-1");
        assert_eq!(d.progress, Some(0.5));
        assert_eq!(d.progress_message.as_deref(), Some("halfway"));
        assert!(d.status.is_none());
        assert!(!d.is_terminal());
    }

    #[test]
    fn job_delta_completed_is_terminal() {
        let d = JobDelta::completed("job-1", serde_json::json!({"ok": true}));
        assert!(d.is_terminal());
        assert_eq!(d.status, Some(JobStatus::Completed));
    }

    #[test]
    fn job_delta_failed_is_terminal() {
        let d = JobDelta::failed("job-1", "boom");
        assert!(d.is_terminal());
        assert_eq!(d.status, Some(JobStatus::Failed));
        assert_eq!(d.error.as_deref(), Some("boom"));
    }

    #[test]
    fn create_job_request_omits_optional_fields_when_none() {
        let req = CreateJobRequest {
            capability: "plan_trip".into(),
            submitted_payload: serde_json::json!({}),
            submitted_by: "client-1".into(),
            max_retries: None,
            max_duration: None,
            total_deadline: None,
            owner_instance_id: None,
        };
        let s = serde_json::to_string(&req).unwrap();
        assert!(s.contains("\"capability\":\"plan_trip\""));
        assert!(!s.contains("max_retries"));
        assert!(!s.contains("owner_instance_id"));
    }

    #[test]
    fn job_delta_omits_none_fields() {
        let d = JobDelta::progress("job-1", 0.25, None);
        let s = serde_json::to_string(&d).unwrap();
        assert!(!s.contains("status"));
        assert!(!s.contains("result"));
        assert!(!s.contains("error"));
        assert!(!s.contains("progress_message"));
    }

    #[test]
    fn backend_error_variants_display() {
        let e = BackendError::NotFound("xyz".into());
        assert!(e.to_string().contains("not found"));
        let e = BackendError::Conflict("terminal".into());
        assert!(e.to_string().contains("conflict"));
        let e = BackendError::BackendUnavailable("down".into());
        assert!(e.to_string().contains("unavailable"));
        let e = BackendError::Server(502, "bad gateway".into());
        assert!(e.to_string().contains("502"));
        let e = BackendError::Other("weird".into());
        assert!(e.to_string().contains("weird"));
    }

    #[test]
    fn backend_error_is_transient_classification() {
        // Transient: anything that can self-heal during a registry rollover.
        assert!(BackendError::BackendUnavailable("503".into()).is_transient());
        assert!(BackendError::Server(500, "ise".into()).is_transient());
        assert!(BackendError::Server(502, "bad gw".into()).is_transient());
        assert!(BackendError::Server(504, "gw timeout".into()).is_transient());

        // NOT transient: caller-visible terminal conditions.
        assert!(!BackendError::NotFound("missing".into()).is_transient());
        assert!(!BackendError::Conflict("term".into()).is_transient());
        assert!(!BackendError::Other("HTTP 400: bad".into()).is_transient());
    }

    #[test]
    fn job_deserializes_from_minimal_json() {
        let s = r#"{
            "id": "abc",
            "capability": "plan_trip",
            "status": "working",
            "submitted_payload": {},
            "attempt_count": 0,
            "max_retries": 1,
            "submitted_at": 1730000000,
            "submitted_by": "client-1"
        }"#;
        let job: Job = serde_json::from_str(s).unwrap();
        assert_eq!(job.id, "abc");
        assert_eq!(job.status, JobStatus::Working);
        assert!(job.owner_instance_id.is_none());
    }

    #[test]
    fn registry_backend_constructs() {
        let b = RegistryHttpBackend::new("http://localhost:9000/").unwrap();
        assert_eq!(b.base_url, "http://localhost:9000");
    }
}

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
    /// Claim generation this delta was produced under (from the claim
    /// response). Stamped by [`crate::jobs::JobController`] onto every
    /// delta it flushes when the controller carries an epoch. `None`
    /// (old SDKs, or a push-mode inbound job that was never claimed) is
    /// omitted from the wire and the registry falls back to owner-only
    /// validation — we never fabricate a bare `0` the registry didn't mint.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub claim_epoch: Option<i64>,
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
            claim_epoch: None,
            status: None,
            progress: Some(progress),
            progress_message: message,
            result: None,
            error: None,
        }
    }

    /// Construct an `input_required` delta (non-terminal). Transitions a
    /// running job to `input_required` status, signalling the consumer that
    /// the handler is blocked awaiting an external answer (typically supplied
    /// via `post_event` + drained by `recv_event`). The optional `message`
    /// rides the existing `progress_message` field — no new wire field. The
    /// registry lease-extends on this delta (`ApplyJobDeltas` in
    /// `ent_service_jobs.go`); the job stays live, so this is NOT terminal.
    pub fn input_required(id: impl Into<String>, message: Option<String>) -> Self {
        Self {
            id: id.into(),
            claim_epoch: None,
            status: Some(JobStatus::InputRequired),
            progress: None,
            progress_message: message,
            result: None,
            error: None,
        }
    }

    /// Construct a terminal `completed` delta with a result payload.
    pub fn completed(id: impl Into<String>, result: serde_json::Value) -> Self {
        Self {
            id: id.into(),
            claim_epoch: None,
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
            claim_epoch: None,
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

/// Registry rejection reason (matches `JobDeltaRejectionClaimSuperseded` in
/// `src/core/registry/ent_service_jobs.go` and the `409` body `error` on the
/// executor-read path) signalling the delta's / reader's `(owner, epoch)`
/// pair was fenced by a newer claim. The controller maps this to the job's
/// cancel token so the superseded handler aborts.
pub const CLAIM_SUPERSEDED_REASON: &str = "claim_superseded";

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
    /// Monotonic claim generation minted by the registry on THIS claim
    /// (bumped +1 on every successful claim / re-claim). The owner echoes
    /// it on `/jobs/batch` deltas and on executor reads of
    /// `GET /jobs/{id}/events`; the registry fences a stale `(owner,
    /// claim_epoch)` pair as `claim_superseded`.
    ///
    /// `#[serde(default)]` ⇒ an OLD registry that predates epochs omits the
    /// field and this deserializes to `None`; the controller then runs
    /// byte-identical legacy behavior (no identity on reads, no epoch on
    /// deltas). We never fabricate a `0` the registry didn't mint.
    #[serde(default)]
    pub claim_epoch: Option<i64>,
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

/// Request body for `POST /jobs/{id}/events`. Append-only event posted into
/// a running job's event log; the executing handler drains these via the
/// `recv_event` long-poll. `payload` is arbitrary JSON; `trace_context`
/// carries W3C trace propagation so the receiver can link a child span.
#[derive(Debug, Clone, Serialize)]
pub struct JobEventPostRequest {
    #[serde(rename = "type")]
    pub event_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payload: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trace_context: Option<serde_json::Value>,
}

/// Response from `POST /jobs/{id}/events`. `seq` is the server-assigned
/// per-job monotonic sequence number; `created_at` is Unix epoch seconds.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobEventReceipt {
    pub job_id: String,
    pub seq: i64,
    pub created_at: i64,
}

/// A single event row from a job's event log
/// (returned by `GET /jobs/{id}/events`).
///
/// `created_at` is Unix epoch seconds — matches the rest of the wire
/// surface (`submitted_at`, `lease_expires_at`, etc.).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobEvent {
    pub job_id: String,
    pub seq: i64,
    #[serde(rename = "type")]
    pub event_type: String,
    #[serde(default)]
    pub payload: Option<serde_json::Value>,
    #[serde(default)]
    pub trace_context: Option<serde_json::Value>,
    #[serde(default)]
    pub posted_by: Option<String>,
    pub created_at: i64,
}

/// Response from `GET /jobs/{id}/events`. `events` is in ascending-seq
/// order; `next_after` is the watermark to feed back as `after` on the
/// next round-trip (the seq of the last returned event, or the same
/// `after` the caller sent if no events arrived).
#[derive(Debug, Clone, Deserialize)]
pub struct JobEventListResponse {
    #[serde(default)]
    pub events: Vec<JobEvent>,
    pub next_after: i64,
}

/// Full job record (`Job` schema).
#[derive(Debug, Clone, Serialize, Deserialize)]
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

    /// Executor read fenced: the caller's `(instance_id, claim_epoch)` no
    /// longer matches the job's current owner + claim generation — a newer
    /// claim superseded this owner. Surfaced ONLY on the executor read path
    /// of `GET /jobs/{id}/events` (HTTP 409, body `error: claim_superseded`).
    /// Distinct from [`BackendError::Conflict`] so the controller can map it
    /// to a cancel rather than a generic conflict. NOT transient.
    #[error("claim superseded: {0}")]
    ClaimSuperseded(String),

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

    /// Long-poll for events on a job (`GET /jobs/{id}/events`). Returns
    /// events with `seq > after`. If `types` is `Some`, only events whose
    /// `event_type` matches one of the given strings are returned (the
    /// registry filters server-side via the `types` query param). `wait`
    /// caps at 60s registry-side — callers requesting longer waits should
    /// loop. `limit` caps at 500.
    ///
    /// `identity`: executor vs. observer read.
    /// * `Some((instance_id, claim_epoch))` — an **executor read**: BOTH
    ///   params are sent so the registry fences the read against the job's
    ///   current owner + claim generation (a stale pair returns
    ///   [`BackendError::ClaimSuperseded`]) AND extends the lease
    ///   (poll-liveness). Only the owning [`crate::jobs::JobController`]
    ///   supplies this, and only when it carries a real claim epoch.
    /// * `None` — an **observer read** (`JobProxy`, A2A, UI, `meshctl`):
    ///   no identity params, no lease side-effects, served unchanged.
    async fn list_job_events(
        &self,
        job_id: &str,
        after: i64,
        types: Option<&[String]>,
        wait: Duration,
        limit: usize,
        identity: Option<(&str, i64)>,
    ) -> Result<JobEventListResponse, BackendError>;

    /// Anyone-side: post an event into a running job's event log
    /// (`POST /jobs/{id}/events`). Returns the server-assigned `seq` and
    /// `created_at`. Rejected with `Conflict` if the job is already in a
    /// terminal state.
    async fn post_job_event(
        &self,
        job_id: &str,
        event_type: &str,
        payload: Option<serde_json::Value>,
        trace_context: Option<serde_json::Value>,
    ) -> Result<JobEventReceipt, BackendError>;
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

    async fn list_job_events(
        &self,
        job_id: &str,
        after: i64,
        types: Option<&[String]>,
        wait: Duration,
        limit: usize,
        identity: Option<(&str, i64)>,
    ) -> Result<JobEventListResponse, BackendError> {
        let url = format!("{}/jobs/{}/events", self.base_url, job_id);
        // Registry caps `wait` at 60s — clamp client-side so we don't
        // round-trip a value the registry will silently truncate.
        let wait_secs = wait.as_secs().min(60);
        let mut req = self.client.get(&url).query(&[
            ("after", after.to_string()),
            ("wait", wait_secs.to_string()),
            ("limit", limit.to_string()),
        ]);
        if let Some(ts) = types {
            if !ts.is_empty() {
                req = req.query(&[("types", ts.join(","))]);
            }
        }
        // Executor read: send BOTH instance_id and claim_epoch so the
        // registry fences + lease-extends. Absent ⇒ anonymous observer read
        // (byte-identical to legacy). Both-or-neither is enforced by taking
        // a single `(instance_id, epoch)` tuple.
        if let Some((instance_id, claim_epoch)) = identity {
            req = req.query(&[
                ("instance_id", instance_id.to_string()),
                ("claim_epoch", claim_epoch.to_string()),
            ]);
        }
        // Per-request timeout > registry's long-poll window so the HTTP
        // call doesn't time out before the registry replies. Pad by 10s
        // beyond the requested wait to absorb network jitter.
        let req = req.timeout(Duration::from_secs(wait_secs + 10));
        debug!(
            "GET {} (after={}, wait={}s, limit={}, types={:?}, executor={})",
            url, after, wait_secs, limit, types, identity.is_some()
        );
        let resp = req.send().await?;
        // Executor read fenced by a newer claim: the registry returns HTTP
        // 409 with body `{"error":"claim_superseded", ...}`. Classify it as
        // the dedicated cancel-firing variant ONLY when BOTH:
        //   (a) this was an executor read (identity supplied), AND
        //   (b) the body actually carries the registry's claim_superseded
        //       marker.
        // A bare 409 from an ingress / proxy — or ANY 409 on an anonymous
        // observer read — must NOT cancel a healthy handler. It falls through
        // to `classify_error` (a generic Conflict), where a genuine
        // fence-cancel never happens (issue #1252 review, item 2).
        if identity.is_some() && resp.status().as_u16() == 409 {
            let body = resp.text().await.unwrap_or_default();
            let is_superseded = serde_json::from_str::<serde_json::Value>(&body)
                .ok()
                .and_then(|v| {
                    v.get("error")
                        .and_then(|e| e.as_str())
                        .map(|s| s == CLAIM_SUPERSEDED_REASON)
                })
                .unwrap_or(false);
            if is_superseded {
                return Err(BackendError::ClaimSuperseded(body));
            }
            // Not the registry's fence marker — a generic conflict from some
            // intermediary. Mirror classify_error's 409 branch (Conflict);
            // never a cancel-firing ClaimSuperseded.
            return Err(BackendError::Conflict(body));
        }
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        Ok(resp.json::<JobEventListResponse>().await?)
    }

    async fn post_job_event(
        &self,
        job_id: &str,
        event_type: &str,
        payload: Option<serde_json::Value>,
        trace_context: Option<serde_json::Value>,
    ) -> Result<JobEventReceipt, BackendError> {
        let url = format!("{}/jobs/{}/events", self.base_url, job_id);
        let body = JobEventPostRequest {
            event_type: event_type.to_string(),
            payload,
            trace_context,
        };
        debug!("POST {} (type={})", url, event_type);
        let resp = self.client.post(&url).json(&body).send().await?;
        if !resp.status().is_success() {
            return Err(Self::classify_error(resp).await);
        }
        Ok(resp.json::<JobEventReceipt>().await?)
    }
}

// =============================================================================
// Shared helpers
// =============================================================================

/// Validate a caller-supplied `timeout_secs` (`f64`) and convert it into an
/// `Option<Duration>`. Shared by the three binding-layer `parse_*timeout_secs`
/// helpers (`jobs_py.rs`, `jobs_napi.rs`, `jobs_ffi.rs`) so the
/// NaN/Inf/negative/overflow policy lives in one place.
///
/// `Duration::from_secs_f64` panics on negative, NaN, infinite, or
/// out-of-range inputs; this helper traps those and returns a clean `Err`
/// string instead so a typo'd literal can't crash the runtime. The final
/// conversion uses the fallible `try_from_secs_f64` so finite-but-huge values
/// (e.g. `f64::MAX`) reject cleanly instead of panicking.
///
/// `negative_is_none` selects the policy for `secs < 0.0`: the C ABI uses a
/// negative sentinel to express `Option<Duration>::None` over a boundary that
/// cannot pass `null` doubles (`true`), whereas the PyO3 / napi helpers treat
/// negatives as errors (`false`).
pub(crate) fn validate_secs_to_duration(
    secs: f64,
    negative_is_none: bool,
) -> Result<Option<Duration>, String> {
    if secs.is_nan() || secs.is_infinite() {
        return Err(format!("timeout_secs must be a finite number, got {secs}"));
    }
    if secs < 0.0 {
        if negative_is_none {
            return Ok(None);
        }
        return Err(format!("timeout_secs must be non-negative, got {secs}"));
    }
    Duration::try_from_secs_f64(secs)
        .map(Some)
        .map_err(|e| format!("timeout_secs out of range: {e} (got {secs})"))
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
    fn job_delta_input_required_constructor() {
        let d = JobDelta::input_required("job-1", Some("need approval".into()));
        assert_eq!(d.id, "job-1");
        assert_eq!(d.status, Some(JobStatus::InputRequired));
        assert_eq!(d.progress_message.as_deref(), Some("need approval"));
        assert!(d.progress.is_none());
        assert!(d.result.is_none());
        assert!(d.error.is_none());
        // input_required is NON-terminal — the handler keeps running.
        assert!(!d.is_terminal());
        // Status serializes as snake_case "input_required".
        let v = serde_json::to_value(&d).unwrap();
        assert_eq!(v["status"], serde_json::json!("input_required"));
        assert_eq!(v["progress_message"], serde_json::json!("need approval"));
    }

    #[test]
    fn job_delta_input_required_omits_message_when_none() {
        let d = JobDelta::input_required("job-1", None);
        assert_eq!(d.status, Some(JobStatus::InputRequired));
        assert!(d.progress_message.is_none());
        let s = serde_json::to_string(&d).unwrap();
        assert!(s.contains("\"status\":\"input_required\""));
        assert!(!s.contains("progress_message"));
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
        // Epoch omitted when None (legacy owner-only path).
        assert!(!s.contains("claim_epoch"));
    }

    #[test]
    fn job_delta_serializes_claim_epoch_when_set() {
        let mut d = JobDelta::progress("job-1", 0.25, None);
        d.claim_epoch = Some(3);
        let v = serde_json::to_value(&d).unwrap();
        assert_eq!(v["claim_epoch"], serde_json::json!(3));
        // A bare 0 IS a legitimate epoch when the registry minted it — must
        // still serialize (only None is omitted).
        d.claim_epoch = Some(0);
        let s = serde_json::to_string(&d).unwrap();
        assert!(s.contains("\"claim_epoch\":0"));
    }

    #[test]
    fn claimed_job_deserializes_with_and_without_epoch() {
        // New registry: claim_epoch present.
        let with = r#"{"id":"j","submitted_payload":{},"attempt_count":1,"claim_epoch":5}"#;
        let cj: ClaimedJob = serde_json::from_str(with).unwrap();
        assert_eq!(cj.claim_epoch, Some(5));
        // Old registry (version skew): field absent ⇒ None ⇒ legacy path.
        let without = r#"{"id":"j","submitted_payload":{},"attempt_count":1}"#;
        let cj: ClaimedJob = serde_json::from_str(without).unwrap();
        assert_eq!(cj.claim_epoch, None);
    }

    #[test]
    fn claim_superseded_is_not_transient() {
        assert!(!BackendError::ClaimSuperseded("x".into()).is_transient());
    }

    // ---- HTTP-level 409 classification (issue #1252 review, item 2) ---------
    //
    // Only an EXECUTOR read (identity supplied) whose 409 body carries the
    // registry's `claim_superseded` marker becomes the cancel-firing
    // ClaimSuperseded. A bare/ingress 409, or ANY 409 on an anonymous
    // observer read, must be a generic Conflict — never cancel a healthy
    // handler.

    #[tokio::test]
    async fn executor_read_409_with_marker_is_claim_superseded() {
        let mut server = mockito::Server::new_async().await;
        let m = server
            .mock("GET", mockito::Matcher::Any)
            .with_status(409)
            .with_header("content-type", "application/json")
            .with_body(r#"{"error":"claim_superseded","timestamp":"2026-01-01T00:00:00Z"}"#)
            .create_async()
            .await;
        let backend = RegistryHttpBackend::new(&server.url()).unwrap();
        let err = backend
            .list_job_events("j1", 0, None, Duration::from_secs(0), 100, Some(("inst-1", 1)))
            .await
            .unwrap_err();
        assert!(
            matches!(err, BackendError::ClaimSuperseded(_)),
            "executor 409 with the marker must be ClaimSuperseded; got {err:?}"
        );
        m.assert_async().await;
    }

    #[tokio::test]
    async fn executor_read_409_without_marker_is_conflict_not_superseded() {
        let mut server = mockito::Server::new_async().await;
        server
            .mock("GET", mockito::Matcher::Any)
            .with_status(409)
            .with_body("upstream conflict from an ingress/proxy")
            .create_async()
            .await;
        let backend = RegistryHttpBackend::new(&server.url()).unwrap();
        let err = backend
            .list_job_events("j1", 0, None, Duration::from_secs(0), 100, Some(("inst-1", 1)))
            .await
            .unwrap_err();
        assert!(
            matches!(err, BackendError::Conflict(_)),
            "a non-marker 409 must NOT fence-cancel a healthy handler; got {err:?}"
        );
    }

    #[tokio::test]
    async fn observer_read_409_is_never_claim_superseded() {
        let mut server = mockito::Server::new_async().await;
        // Even a body carrying the marker must not fence an OBSERVER read
        // (identity=None) — observers never participate in claim fencing.
        server
            .mock("GET", mockito::Matcher::Any)
            .with_status(409)
            .with_body(r#"{"error":"claim_superseded"}"#)
            .create_async()
            .await;
        let backend = RegistryHttpBackend::new(&server.url()).unwrap();
        let err = backend
            .list_job_events("j1", 0, None, Duration::from_secs(0), 100, None)
            .await
            .unwrap_err();
        assert!(
            matches!(err, BackendError::Conflict(_)),
            "observer 409 must be Conflict, never ClaimSuperseded; got {err:?}"
        );
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

    #[test]
    fn job_event_post_request_serializes_type_field() {
        // `type` is a reserved word in Rust — must be renamed via serde.
        let req = JobEventPostRequest {
            event_type: "extend_deadline".into(),
            payload: Some(serde_json::json!({"secs": 30})),
            trace_context: None,
        };
        let s = serde_json::to_string(&req).unwrap();
        assert!(s.contains("\"type\":\"extend_deadline\""));
        assert!(s.contains("\"payload\""));
        // None fields omitted.
        assert!(!s.contains("trace_context"));
    }

    #[test]
    fn job_event_deserializes_from_registry_shape() {
        // Mirrors the OpenAPI JobEvent schema field-for-field.
        let s = r#"{
            "job_id": "j-1",
            "seq": 7,
            "type": "extend_deadline",
            "payload": {"secs": 30},
            "trace_context": {"traceparent": "00-...-01"},
            "posted_by": "agent-x",
            "created_at": 1729999500
        }"#;
        let ev: JobEvent = serde_json::from_str(s).unwrap();
        assert_eq!(ev.job_id, "j-1");
        assert_eq!(ev.seq, 7);
        assert_eq!(ev.event_type, "extend_deadline");
        assert_eq!(ev.posted_by.as_deref(), Some("agent-x"));
        assert_eq!(ev.created_at, 1729999500);
    }

    #[test]
    fn job_event_list_response_deserializes_with_empty_events() {
        let s = r#"{"events": [], "next_after": 0}"#;
        let resp: JobEventListResponse = serde_json::from_str(s).unwrap();
        assert!(resp.events.is_empty());
        assert_eq!(resp.next_after, 0);
    }

    // -------------------------------------------------------------------------
    // Wire-shape byte-identity guard for the binding-layer serializers.
    //
    // The Python / Node(napi) / FFI bindings all route `Job` / `JobEvent` /
    // `JobEventReceipt` through serde (`to_value` / `to_string`). These tests
    // pin the serialized shape so a future field/attr change that would alter
    // the dict/JS-object/JSON the SDKs parse fails here first.
    // -------------------------------------------------------------------------

    fn full_job() -> Job {
        Job {
            id: "j-1".into(),
            capability: "plan_trip".into(),
            owner_instance_id: Some("inst-7".into()),
            status: JobStatus::Working,
            progress: Some(0.5),
            progress_message: Some("halfway".into()),
            result: Some(serde_json::json!({"ok": true})),
            error: Some("boom".into()),
            submitted_payload: serde_json::json!({"q": 1}),
            attempt_count: 2,
            max_retries: 3,
            max_duration: Some(120),
            total_deadline: Some(1_730_000_500),
            lease_expires_at: Some(1_730_000_100),
            last_heartbeat_at: Some(1_730_000_050),
            submitted_at: 1_730_000_000,
            submitted_by: "client-1".into(),
        }
    }

    const JOB_KEYS: [&str; 17] = [
        "id",
        "capability",
        "owner_instance_id",
        "status",
        "progress",
        "progress_message",
        "result",
        "error",
        "submitted_payload",
        "attempt_count",
        "max_retries",
        "max_duration",
        "total_deadline",
        "lease_expires_at",
        "last_heartbeat_at",
        "submitted_at",
        "submitted_by",
    ];

    #[test]
    fn job_serializes_full_shape() {
        let v = serde_json::to_value(&full_job()).unwrap();
        let obj = v.as_object().expect("Job serializes to a JSON object");
        assert_eq!(obj.len(), JOB_KEYS.len());
        for k in JOB_KEYS {
            assert!(obj.contains_key(k), "missing key: {k}");
        }
        assert_eq!(obj["id"], serde_json::json!("j-1"));
        assert_eq!(obj["capability"], serde_json::json!("plan_trip"));
        assert_eq!(obj["owner_instance_id"], serde_json::json!("inst-7"));
        assert_eq!(obj["status"], serde_json::json!("working"));
        assert_eq!(obj["progress"], serde_json::json!(0.5));
        assert_eq!(obj["progress_message"], serde_json::json!("halfway"));
        assert_eq!(obj["result"], serde_json::json!({"ok": true}));
        assert_eq!(obj["error"], serde_json::json!("boom"));
        assert_eq!(obj["submitted_payload"], serde_json::json!({"q": 1}));
        assert_eq!(obj["attempt_count"], serde_json::json!(2));
        assert_eq!(obj["max_retries"], serde_json::json!(3));
        assert_eq!(obj["max_duration"], serde_json::json!(120));
        assert_eq!(obj["total_deadline"], serde_json::json!(1_730_000_500i64));
        assert_eq!(obj["lease_expires_at"], serde_json::json!(1_730_000_100i64));
        assert_eq!(obj["last_heartbeat_at"], serde_json::json!(1_730_000_050i64));
        assert_eq!(obj["submitted_at"], serde_json::json!(1_730_000_000i64));
        assert_eq!(obj["submitted_by"], serde_json::json!("client-1"));
    }

    #[test]
    fn job_serializes_minimal_shape() {
        // All Options None: every key MUST still be present (the Python SDK
        // indexes strictly, e.g. `snapshot["progress"]`); the Option fields
        // serialize to `null` (NO `skip_serializing_if`).
        let job = Job {
            id: "j-2".into(),
            capability: "cap".into(),
            owner_instance_id: None,
            status: JobStatus::Completed,
            progress: None,
            progress_message: None,
            result: None,
            error: None,
            submitted_payload: serde_json::json!({}),
            attempt_count: 0,
            max_retries: 0,
            max_duration: None,
            total_deadline: None,
            lease_expires_at: None,
            last_heartbeat_at: None,
            submitted_at: 1,
            submitted_by: "c".into(),
        };
        let v = serde_json::to_value(&job).unwrap();
        let obj = v.as_object().unwrap();
        assert_eq!(obj.len(), JOB_KEYS.len());
        for k in JOB_KEYS {
            assert!(obj.contains_key(k), "missing key: {k}");
        }
        // The keep-nulls guarantee: present-as-null, not omitted.
        for k in [
            "owner_instance_id",
            "progress",
            "progress_message",
            "result",
            "error",
            "max_duration",
            "total_deadline",
            "lease_expires_at",
            "last_heartbeat_at",
        ] {
            assert_eq!(obj[k], serde_json::Value::Null, "key {k} should be null");
        }
        assert_eq!(obj["status"], serde_json::json!("completed"));
    }

    #[test]
    fn job_event_serializes_shape() {
        // Key is `type` (renamed), not `event_type`. payload/trace_context
        // present-as-null when None.
        let ev = JobEvent {
            job_id: "j-1".into(),
            seq: 7,
            event_type: "extend_deadline".into(),
            payload: None,
            trace_context: None,
            posted_by: None,
            created_at: 1_729_999_500,
        };
        let v = serde_json::to_value(&ev).unwrap();
        let obj = v.as_object().unwrap();
        assert_eq!(obj.len(), 7);
        assert!(obj.contains_key("type"));
        assert!(!obj.contains_key("event_type"));
        assert_eq!(obj["type"], serde_json::json!("extend_deadline"));
        assert_eq!(obj["job_id"], serde_json::json!("j-1"));
        assert_eq!(obj["seq"], serde_json::json!(7));
        assert_eq!(obj["payload"], serde_json::Value::Null);
        assert_eq!(obj["trace_context"], serde_json::Value::Null);
        assert_eq!(obj["posted_by"], serde_json::Value::Null);
        assert_eq!(obj["created_at"], serde_json::json!(1_729_999_500i64));
    }

    #[test]
    fn job_event_receipt_serializes_shape() {
        let receipt = JobEventReceipt {
            job_id: "j-1".into(),
            seq: 3,
            created_at: 1_729_999_000,
        };
        let v = serde_json::to_value(&receipt).unwrap();
        let obj = v.as_object().unwrap();
        assert_eq!(obj.len(), 3);
        assert_eq!(obj["job_id"], serde_json::json!("j-1"));
        assert_eq!(obj["seq"], serde_json::json!(3));
        assert_eq!(obj["created_at"], serde_json::json!(1_729_999_000i64));
    }

    #[test]
    fn progress_f32_roundtrips() {
        let mut job = full_job();
        job.progress = Some(0.5);
        let v = serde_json::to_value(&job).unwrap();
        assert_eq!(v["progress"], serde_json::json!(0.5));
        assert_eq!(v["progress"].as_f64(), Some(0.5));
    }

    #[test]
    fn validate_secs_to_duration_edge_cases() {
        assert_eq!(
            validate_secs_to_duration(0.0, false).unwrap(),
            Some(Duration::from_secs(0))
        );
        assert_eq!(
            validate_secs_to_duration(1.5, false).unwrap(),
            Some(Duration::from_millis(1500))
        );
        // Negative: errors when negative_is_none=false, None when true.
        assert!(validate_secs_to_duration(-1.0, false).is_err());
        assert_eq!(validate_secs_to_duration(-1.0, true).unwrap(), None);
        // NaN / Inf always error regardless of negative policy.
        assert!(validate_secs_to_duration(f64::NAN, false).is_err());
        assert!(validate_secs_to_duration(f64::NAN, true).is_err());
        assert!(validate_secs_to_duration(f64::INFINITY, false).is_err());
        assert!(validate_secs_to_duration(f64::INFINITY, true).is_err());
        // Finite-but-huge overflows Duration; message must say "out of range".
        let err = validate_secs_to_duration(f64::MAX, false).expect_err("overflow");
        assert!(
            err.contains("out of range"),
            "expected 'out of range', got: {err}"
        );
    }
}

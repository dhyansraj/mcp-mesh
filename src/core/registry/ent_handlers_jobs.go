package registry

// Handlers for the MeshJob substrate (long-running async tool calls). See
// MESHJOB_DESIGN.org for the full state machine, lease semantics, retry
// rules, and the push/pull submission modes.

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/registry/generated"
)

// cancelForwardTimeout is the wall-clock cap on the registry → owner
// HTTP forward in CancelJob. Short on purpose: if the owner doesn't ack
// quickly we proceed to mark the row cancelled regardless. The
// heartbeat/lease + sweep loop guarantees correctness even when the
// forward is dropped.
const cancelForwardTimeout = 5 * time.Second

// CreateJob implements POST /jobs.
//
// Two submission modes are supported through a single endpoint:
//   - Push mode: the request includes `owner_instance_id` (the submitter has
//     pre-resolved a target replica via mesh dep resolution). The job row is
//     created with that instance pinned as owner.
//   - Pull mode: `owner_instance_id` is omitted. The row is created with
//     owner NULL; a capability replica must atomically claim it via
//     POST /jobs/claim before execution.
func (h *EntBusinessLogicHandlers) CreateJob(c *gin.Context) {
	var req generated.CreateJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	if req.Capability == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "capability is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.SubmittedBy == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "submitted_by is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.SubmittedPayload == nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "submitted_payload is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	maxRetries := 1
	if req.MaxRetries != nil {
		if *req.MaxRetries < 0 {
			c.JSON(http.StatusBadRequest, generated.ErrorResponse{
				Error:     "max_retries must be non-negative",
				Timestamp: time.Now().UTC(),
			})
			return
		}
		maxRetries = *req.MaxRetries
	}
	if req.MaxDuration != nil && *req.MaxDuration < 1 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "max_duration must be positive",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	created, err := h.entService.CreateJob(c.Request.Context(), &CreateJobInput{
		ID:               uuid.NewString(),
		Capability:       req.Capability,
		SubmittedBy:      req.SubmittedBy,
		SubmittedPayload: req.SubmittedPayload,
		OwnerInstanceID:  req.OwnerInstanceId,
		MaxRetries:       maxRetries,
		MaxDuration:      req.MaxDuration,
		TotalDeadline:    req.TotalDeadline,
	})
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to create job: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	resp := generated.CreateJobResponse{
		Id:              created.ID,
		Status:          generated.JobStatus(string(created.Status)),
		OwnerInstanceId: created.OwnerInstanceID,
	}
	c.JSON(http.StatusCreated, resp)
}

// GetJob implements GET /jobs/{job_id}. All status reads terminate here —
// no replica-side caching, no owner-bound routing. Possession of the
// job_id (UUID) is the capability for read access (presigned-URL semantics
// — see Auth model in the design doc).
func (h *EntBusinessLogicHandlers) GetJob(c *gin.Context, jobId string) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	j, err := h.entService.GetJob(c.Request.Context(), jobId)
	if err != nil {
		if ent.IsNotFound(err) {
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
			return
		}
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to fetch job: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	c.JSON(http.StatusOK, jobToAPI(j))
}

// SubmitJobBatch implements POST /jobs/batch.
//
// Accepts a coalesced batch of per-job deltas from a single producer
// instance. Each delta is applied independently — partial success is the
// spec; rejections are surfaced per-id with a stable reason code.
func (h *EntBusinessLogicHandlers) SubmitJobBatch(c *gin.Context) {
	var req generated.JobBatchRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.InstanceId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "instance_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if len(req.Deltas) == 0 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "deltas must not be empty",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	deltas := make([]JobDeltaInput, 0, len(req.Deltas))
	for _, d := range req.Deltas {
		if d.Id == "" {
			c.JSON(http.StatusBadRequest, generated.ErrorResponse{
				Error:     "every delta requires a non-empty id",
				Timestamp: time.Now().UTC(),
			})
			return
		}
		in := JobDeltaInput{
			ID:              d.Id,
			ProgressMessage: d.ProgressMessage,
			Error:           d.Error,
		}
		if d.Progress != nil {
			p := float64(*d.Progress)
			in.Progress = &p
		}
		if d.Status != nil {
			s := string(*d.Status)
			in.Status = &s
		}
		if d.Result != nil {
			in.Result = *d.Result
		}
		deltas = append(deltas, in)
	}

	accepted, rejections, err := h.entService.ApplyJobDeltas(c.Request.Context(), req.InstanceId, deltas)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to apply deltas: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	resp := generated.JobBatchResponse{Accepted: accepted}
	resp.Rejected = make([]struct {
		Id     string `json:"id"`
		Reason string `json:"reason"`
	}, 0, len(rejections))
	for _, r := range rejections {
		resp.Rejected = append(resp.Rejected, struct {
			Id     string `json:"id"`
			Reason string `json:"reason"`
		}{Id: r.ID, Reason: r.Reason})
	}
	c.JSON(http.StatusOK, resp)
}

// ClaimJobs implements POST /jobs/claim.
//
// Single-claim per round-trip (see Resolved Decisions). Race-free across
// concurrent claimers via guarded UPDATE inside the service layer; "no
// work available" is a 200 with claimed=[] (not an error).
func (h *EntBusinessLogicHandlers) ClaimJobs(c *gin.Context) {
	var req generated.ClaimJobsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.Capability == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "capability is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.InstanceId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "instance_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	claimed, err := h.entService.ClaimNextJob(c.Request.Context(), req.Capability, req.InstanceId)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to claim job: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	resp := generated.ClaimJobsResponse{Claimed: []generated.ClaimedJob{}}
	if claimed != nil {
		entry := generated.ClaimedJob{
			Id:               claimed.ID,
			AttemptCount:     claimed.AttemptCount,
			SubmittedPayload: claimed.SubmittedPayload,
			MaxDuration:      claimed.MaxDuration,
		}
		if claimed.LeaseExpiresAt != nil {
			v := int(claimed.LeaseExpiresAt.Unix())
			entry.LeaseExpiresAt = &v
		}
		resp.Claimed = append(resp.Claimed, entry)
	}
	c.JSON(http.StatusOK, resp)
}

// CancelJob implements POST /jobs/{job_id}/cancel.
//
// Three scenarios per the design:
//   - Owned (alive): registry forwards cancel to the owner replica's HTTP
//     endpoint, then marks the row cancelled regardless of forward outcome
//     (best-effort forward; lease/sweep guarantees eventual correctness).
//   - Unowned (orphan / pre-claim): registry directly marks cancelled.
//   - Already terminal: 409 Conflict.
func (h *EntBusinessLogicHandlers) CancelJob(c *gin.Context, jobId string) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Body is optional. Absence/empty body is fine.
	var req generated.CancelJobRequest
	if c.Request.ContentLength > 0 {
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, generated.ErrorResponse{
				Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
				Timestamp: time.Now().UTC(),
			})
			return
		}
	}
	reason := ""
	if req.Reason != nil {
		reason = *req.Reason
	}

	updated, prevOwner, err := h.entService.CancelJob(c.Request.Context(), jobId, reason)
	if err != nil {
		switch {
		case ent.IsNotFound(err):
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
		case errors.Is(err, ErrJobAlreadyTerminal):
			c.JSON(http.StatusConflict, generated.ErrorResponse{
				Error:     "job is already in a terminal state",
				Timestamp: time.Now().UTC(),
			})
		default:
			c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
				Error:     fmt.Sprintf("Failed to cancel job: %v", err),
				Timestamp: time.Now().UTC(),
			})
		}
		return
	}

	// Best-effort owner notification. Errors are logged but never affect
	// the response — the registry row is the source of truth, and the
	// owner's lease will time out even if the forward never lands.
	resp := generated.CancelJobResponse{
		Status:                generated.JobStatus(string(updated.Status)),
		ForwardedToInstanceId: prevOwner,
	}
	if prevOwner != nil {
		h.forwardCancelToOwner(c, *prevOwner, jobId, reason)
	}
	c.JSON(http.StatusOK, resp)
}

// forwardCancelToOwner POSTs the cancel to the owner agent's HTTP endpoint
// best-effort. Any failure (agent unknown, unreachable, non-2xx) is logged
// and swallowed: the registry row already shows status=cancelled, and the
// owner's lease will expire if the message is missed.
//
// Scheme handling: when the agent registered an entity_id (i.e. presented
// a TLS client cert at registration time) we dial https with the registry's
// own mTLS bundle. Otherwise we dial http. Mirrors the scheme-selection
// in proxyRequest's isRegisteredAgentEndpoint path.
//
// Trace-header propagation matches the proxy path (#310) — we set the
// well-known headers explicitly rather than going through the
// MCP_MESH_PROPAGATE_HEADERS allowlist because the cancel forward is a
// fixed, registry-internal destination and no operator opt-in is needed.
//
// Goroutine-driven dispatch: the cancel response to the original HTTP
// caller does NOT wait for the forward to land. The registry row is
// already marked cancelled before this is called; the forward is purely
// a best-effort signal to abort an in-flight handler. Spawning the
// forward into a goroutine keeps the public response p99 close to the
// DB write latency rather than the owner-agent round-trip + 5s timeout.
//
// Shutdown coordination: when the handlers were constructed with the
// production ``NewEntBusinessLogicHandlersWithShutdown`` constructor,
// the goroutine derives its HTTP-request context from
// ``h.shutdownCtx`` and registers on ``h.shutdownWG``. ``Server.Stop``
// cancels ``shutdownCtx`` (cleanly aborting in-flight forwards via the
// transport's context-cancellation hook) and then waits on
// ``shutdownWG`` for the goroutines to drain — surfacing any abandoned
// forwards in the log instead of letting them run on after the
// registry is supposedly stopped. When constructed with the legacy
// zero-arg ``NewEntBusinessLogicHandlers`` (tests), the parent context
// falls back to ``context.Background()`` and the WaitGroup is a
// private no-op so the existing best-effort behaviour is preserved.
func (h *EntBusinessLogicHandlers) forwardCancelToOwner(c *gin.Context, ownerInstanceID, jobID, reason string) {
	// Capture the request-scoped values BEFORE detaching: the request
	// context dies when the response is sent, so we copy headers we
	// need and derive the forward context from the server's
	// shutdown-aware context (see struct doc) so a registry stop cleanly
	// aborts in-flight forwards instead of letting them run to their
	// 5s per-call timeout on a goroutine the process can't observe.
	traceID := c.Request.Header.Get("X-Trace-ID")
	parentSpan := c.Request.Header.Get("X-Parent-Span")
	meshTimeout := c.Request.Header.Get("X-Mesh-Timeout")

	parentCtx := h.shutdownCtx
	if parentCtx == nil {
		parentCtx = context.Background()
	}

	// Reserve a slot on the shutdown WaitGroup BEFORE go-statement so a
	// shutdown that races with this handler still observes the goroutine
	// in its Wait. The matching Done() lives at the top of the goroutine
	// via ``defer`` so a panic inside the forward can't leak the slot.
	h.shutdownWG.Add(1)

	go func() {
		defer h.shutdownWG.Done()

		fwdCtx, cancel := context.WithTimeout(parentCtx, cancelForwardTimeout)
		defer cancel()

		agentRow, err := h.entService.GetAgent(fwdCtx, ownerInstanceID)
		if err != nil || agentRow == nil {
			log.Printf("[meshjob] cancel forward skipped: owner %q not found in registry (job=%s, err=%v)", ownerInstanceID, jobID, err)
			return
		}
		if agentRow.HTTPHost == "" || agentRow.HTTPPort == 0 {
			log.Printf("[meshjob] cancel forward skipped: owner %q has no HTTP endpoint registered (job=%s)", ownerInstanceID, jobID)
			return
		}

		// Scheme: https only when the agent has registered an entity_id
		// (mTLS bundle present). Matches the scheme decision baked into
		// the agents-list endpoint and proxyRequest's
		// isRegisteredAgentEndpoint path.
		scheme := "http"
		if agentRow.EntityID != nil && *agentRow.EntityID != "" {
			scheme = "https"
		}
		url := fmt.Sprintf("%s://%s:%d/jobs/%s/cancel", scheme, agentRow.HTTPHost, agentRow.HTTPPort, jobID)

		body := strings.NewReader("")
		if reason != "" {
			// Mirror the on-wire CancelJobRequest shape so the agent runtime
			// can decode the same struct it would on a direct client call.
			body = strings.NewReader(fmt.Sprintf(`{"reason":%q}`, reason))
		}

		req, err := http.NewRequestWithContext(fwdCtx, http.MethodPost, url, body)
		if err != nil {
			log.Printf("[meshjob] cancel forward build failed (owner=%s, job=%s): %v", ownerInstanceID, jobID, err)
			return
		}
		req.Header.Set("Content-Type", "application/json")

		if traceID != "" {
			req.Header.Set("X-Trace-ID", traceID)
		}
		if parentSpan != "" {
			req.Header.Set("X-Parent-Span", parentSpan)
		}
		if meshTimeout != "" {
			req.Header.Set("X-Mesh-Timeout", meshTimeout)
		}

		client, err := h.cancelForwardClient(scheme)
		if err != nil {
			log.Printf("[meshjob] cancel forward TLS init failed (owner=%s, job=%s): %v", ownerInstanceID, jobID, err)
			return
		}

		resp, err := client.Do(req)
		if err != nil {
			// Distinguish a registry-shutdown cancellation from a "real"
			// network error so operators see that the forward was
			// abandoned by us, not lost to an owner-side fault.
			// ``parentCtx.Err()`` is sticky once the parent is cancelled,
			// so checking it here reliably attributes the failure to
			// shutdown even when ``fwdCtx`` reports the wrapped
			// cancellation.
			if parentCtx.Err() != nil {
				log.Printf("[meshjob] cancel forward to %s abandoned: registry shutting down (job=%s, err=%v)", url, jobID, err)
			} else {
				log.Printf("[meshjob] cancel forward to %s failed (job=%s): %v", url, jobID, err)
			}
			return
		}
		defer resp.Body.Close()
		// Drain to allow connection reuse; ignore body content.
		_, _ = io.Copy(io.Discard, resp.Body)
		if resp.StatusCode >= 300 {
			log.Printf("[meshjob] cancel forward to %s returned status %d (job=%s)", url, resp.StatusCode, jobID)
		}
	}()
}

// cancelForwardClient builds a one-shot http.Client for forwarding a
// cancel to an owner agent. For ``https`` targets we attach the same
// mTLS configuration (CA + client cert/key, peer chain verification with
// hostname verification disabled) that proxyRequest uses — the same env
// vars (MCP_MESH_TLS_CA / _CERT / _KEY) gate both code paths so misconfig
// surfaces consistently.
func (h *EntBusinessLogicHandlers) cancelForwardClient(scheme string) (*http.Client, error) {
	client := &http.Client{Timeout: cancelForwardTimeout}
	if scheme != "https" {
		return client, nil
	}

	caPath := os.Getenv("MCP_MESH_TLS_CA")
	certPath := os.Getenv("MCP_MESH_TLS_CERT")
	keyPath := os.Getenv("MCP_MESH_TLS_KEY")
	if caPath == "" || certPath == "" || keyPath == "" {
		return nil, fmt.Errorf("https cancel forward requires MCP_MESH_TLS_CA / MCP_MESH_TLS_CERT / MCP_MESH_TLS_KEY (got ca=%q cert=%q key=%q)", caPath, certPath, keyPath)
	}

	caBytes, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("read CA cert %s: %w", caPath, err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caBytes) {
		return nil, fmt.Errorf("parse CA cert from %s (empty or malformed PEM)", caPath)
	}

	clientCert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("load client cert/key (%s, %s): %w", certPath, keyPath, err)
	}

	tlsConfig := &tls.Config{
		// Skip hostname check (--tls-auto certs are 127.0.0.1/::1 SANs only)
		// but still verify the peer chain against the mesh CA.
		InsecureSkipVerify: true,
		Certificates:       []tls.Certificate{clientCert},
		VerifyConnection: func(cs tls.ConnectionState) error {
			if len(cs.PeerCertificates) == 0 {
				return fmt.Errorf("no peer certificates presented")
			}
			opts := x509.VerifyOptions{
				Roots:         caPool,
				Intermediates: x509.NewCertPool(),
			}
			for _, cert := range cs.PeerCertificates[1:] {
				opts.Intermediates.AddCert(cert)
			}
			_, err := cs.PeerCertificates[0].Verify(opts)
			return err
		},
	}
	client.Transport = &http.Transport{TLSClientConfig: tlsConfig}
	return client, nil
}

// jobToAPI converts an Ent Job entity into the OpenAPI Job representation.
//
// Field mapping notes:
//   - Time fields (submitted_at, lease_expires_at, last_heartbeat_at,
//     total_deadline) are persisted as time.Time but exposed as Unix epoch
//     seconds (`integer`) per the OpenAPI schema.
//   - `progress` is float64 in Ent but float32 in the generated API type.
func jobToAPI(j *ent.Job) generated.Job {
	api := generated.Job{
		Id:               j.ID,
		Capability:       j.Capability,
		Status:           generated.JobStatus(string(j.Status)),
		SubmittedPayload: j.SubmittedPayload,
		AttemptCount:     j.AttemptCount,
		MaxRetries:       j.MaxRetries,
		SubmittedAt:      int(j.SubmittedAt.Unix()),
		OwnerInstanceId:  j.OwnerInstanceID,
		ProgressMessage:  j.ProgressMessage,
		Error:            j.Error,
		MaxDuration:      j.MaxDuration,
	}
	if j.Progress != nil {
		p := float32(*j.Progress)
		api.Progress = &p
	}
	if j.Result != nil {
		r := j.Result
		api.Result = &r
	}
	if j.SubmittedBy != nil {
		api.SubmittedBy = *j.SubmittedBy
	}
	if j.TotalDeadline != nil {
		v := int(j.TotalDeadline.Unix())
		api.TotalDeadline = &v
	}
	if j.LeaseExpiresAt != nil {
		v := int(j.LeaseExpiresAt.Unix())
		api.LeaseExpiresAt = &v
	}
	if j.LastHeartbeatAt != nil {
		v := int(j.LastHeartbeatAt.Unix())
		api.LastHeartbeatAt = &v
	}
	return api
}

// CreateJobInput collects the fields the service layer needs to persist a
// new job row. Mirrors the OpenAPI CreateJobRequest plus a server-generated
// ID so the handler controls UUID minting.
type CreateJobInput struct {
	ID               string
	Capability       string
	SubmittedBy      string
	SubmittedPayload map[string]interface{}
	OwnerInstanceID  *string
	MaxRetries       int
	MaxDuration      *int
	TotalDeadline    *int // Unix epoch seconds; converted to time.Time on persist
}

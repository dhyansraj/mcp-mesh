"""Spawn one Python claim dispatcher per ``@mesh.tool(task=True)``
function on agent startup (Phase 1 — MeshJob substrate).

See :mod:`_mcp_mesh.engine.claim_dispatcher` for the dispatcher itself
and the rationale for the Phase-1 Python implementation (vs the Rust
core's ``ClaimDispatcher`` trait).

Lifecycle note (#bug 2 — local-validation revision)
---------------------------------------------------

This step DISCOVERS task handlers and CONSTRUCTS one
:class:`PythonClaimDispatcher` per handler — but it deliberately does
NOT call ``d.start()`` here. Why?

The startup pipeline runs inside ``asyncio.run(orchestrator.process_once())``
(see ``startup_orchestrator.py``). Any ``asyncio.create_task`` spawned
during that call is bound to the pipeline's one-shot event loop and
gets cancelled when ``asyncio.run`` returns. The persistent FastAPI /
uvicorn loop that serves requests is a *different* event loop on a
different thread — so a task started here would die before serving its
first claim.

The dispatchers are stashed on:

* The pipeline ``context`` under ``"claim_dispatchers"`` — the heartbeat
  task (``rust_heartbeat_task``) starts them on its long-lived
  background-thread loop. This is the *primary* startup path because
  the heartbeat loop's lifetime matches the agent's, and it starts
  *after* this step has populated the context.
* The FastAPI ``app.state.mesh_claim_dispatchers`` — the lifespan
  factory (``lifespan_factory.py``) starts them as a *backup* for
  non-immediate-uvicorn flows. ``PythonClaimDispatcher.start()`` is
  idempotent, so a second start call from the lifespan is a no-op when
  the heartbeat already kicked them off.

Skipped gracefully when no task handlers are registered (every
consumer-only agent) or when ``MCP_MESH_REGISTRY_URL`` is unset.
"""

from __future__ import annotations

import logging
from typing import Any

from ...engine.claim_dispatcher import discover_task_handlers
from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


class JobsClaimWorkersStep(PipelineStep):
    """Discover task handlers and stage a Python claim worker for each.

    Actual ``start()`` happens inside the FastAPI lifespan so the worker
    runs on the long-lived uvicorn event loop (see module docstring).
    """

    def __init__(self) -> None:
        super().__init__(
            name="jobs-claim-workers",
            required=False,
            description=(
                "Stage a Python claim worker for each @mesh.tool(task=True) "
                "function (started by FastAPI lifespan)"
            ),
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="Claim workers")

        registry_url = context.get("registry_url")
        agent_id = context.get("agent_id") or "unknown"
        if not registry_url:
            result.status = PipelineStatus.SKIPPED
            result.message = (
                "Claim workers skipped: no registry_url configured"
            )
            self.logger.info("⚠️ %s", result.message)
            return result

        dispatchers = discover_task_handlers(agent_id, registry_url)
        if not dispatchers:
            # Benign on consumer-only agents (no task=True tools). Use
            # SKIPPED + INFO log level so it doesn't surface as ERROR
            # in the pipeline summary (#bug 6).
            result.status = PipelineStatus.SKIPPED
            result.message = "Claim workers skipped: no task=True handlers"
            self.logger.info("ℹ️ %s", result.message)
            return result

        # Stash on context so the lifespan can pick them up and start
        # them on the persistent uvicorn loop. Also attach to the
        # FastAPI app state when available, so lifespan retrieval is
        # not coupled to the pipeline-context dict.
        existing = context.get("claim_dispatchers", [])
        existing.extend(dispatchers)
        result.add_context("claim_dispatchers", existing)

        app = context.get("fastapi_app")
        if app is not None:
            try:
                app.state.mesh_claim_dispatchers = existing
                self.logger.debug(
                    "Attached %d claim worker(s) to FastAPI app state for "
                    "lifespan-driven startup",
                    len(existing),
                )
            except Exception as e:
                self.logger.debug(
                    "Could not stash claim dispatchers on app.state (%s); "
                    "lifespan will fall back to context-based lookup",
                    e,
                )

        result.message = (
            f"Staged {len(dispatchers)} claim worker(s) (start deferred to "
            f"FastAPI lifespan)"
        )
        self.logger.info("📨 %s", result.message)
        return result

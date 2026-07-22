"""Eager trace-publisher initialization for off-request-path startup.

Issue #1363: the Redis trace publisher was constructed lazily on the FIRST
traced span, and its ``__init__`` runs a SYNC ``block_on`` Redis connect in the
Rust core. On the serving event loop that froze every concurrent request
coroutine for the connect duration (empirically ~118s against a black-holed
telemetry Redis). This step performs that (now hard-bounded) connect ONCE at
agent startup, off the request path, so the request-path lookup is a pure
cached read.

Used by both startup paths — the MCP-agent pipeline and the ``@mesh.route`` API
pipeline. No-op when tracing is disabled. Never fails startup: a telemetry Redis
outage must only pause tracing, never take the agent down.
"""

import asyncio
from typing import Any

from . import PipelineResult, PipelineStep


class TracePublisherInitStep(PipelineStep):
    """Construct the Redis trace-publisher singleton at startup (off the loop)."""

    def __init__(self):
        super().__init__(
            name="trace-publisher-init",
            required=False,  # Telemetry outage must never fail agent startup.
            description="Eagerly initialize the Redis trace publisher off the request path",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="Trace publisher init completed")

        # Local import keeps pipeline import-time cheap.
        from ...tracing.redis_metadata_publisher import (
            init_trace_publisher_at_startup,
        )

        try:
            # The construction does a hard-bounded (~3s) sync block_on Redis
            # connect in the Rust core. Run it on a worker thread so the
            # startup event loop (health/ready endpoints) stays responsive
            # while a down Redis is being probed. init never raises.
            await asyncio.to_thread(init_trace_publisher_at_startup)
            result.message = "Trace publisher initialized (or skipped: tracing disabled)"
            self.logger.debug("Trace publisher startup init complete")
        except Exception as e:
            # Belt-and-suspenders: init_trace_publisher_at_startup already
            # swallows its own errors, but never let this step fail startup.
            result.message = f"Trace publisher init skipped ({e})"
            self.logger.warning("Trace publisher startup init error (continuing): %s", e)

        return result

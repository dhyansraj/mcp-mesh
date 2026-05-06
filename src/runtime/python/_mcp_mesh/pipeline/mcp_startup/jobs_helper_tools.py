"""Auto-register the three MeshJob helper tools on every mesh agent
(Phase 1 — MeshJob substrate).

Per ``MESHJOB_DESIGN.org`` "Helper tool placement: auto-registered on
every mesh agent": ``__mesh_job_status`` / ``__mesh_job_result`` /
``__mesh_job_cancel`` are framework primitives, exposed on every agent
that initializes the mesh runtime — independent of whether that agent
owns any ``task=True`` tools. External MCP clients can call any agent
to poll job status; the call lands at the registry, not at any specific
owner replica.

Registration happens against the user's discovered FastMCP server
instance(s), so the helpers appear in `tools/list` alongside user tools
with the ``__mesh_job_`` prefix marking them framework-internal.

The helpers are thin shims around :class:`mcp_mesh_core.JobProxy` —
all reads / cancels terminate at the registry's ``GET /jobs/{id}`` /
``POST /jobs/{id}/cancel``. No replica-side caching, no owner-bound
routing for reads (per "Status read path" decision in design doc).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


# Tool names — the ``__`` prefix marks them framework-internal so MCP
# clients can filter them out of user-facing tool lists if desired.
_TOOL_NAME_STATUS = "__mesh_job_status"
_TOOL_NAME_RESULT = "__mesh_job_result"
_TOOL_NAME_CANCEL = "__mesh_job_cancel"


def _make_helper_tools(registry_url: str) -> dict[str, Any]:
    """Build the three async helper functions bound to ``registry_url``.

    Returned as a dict ``{tool_name: callable}`` so the caller can
    register them however its FastMCP version prefers (``@app.tool`` /
    ``app.add_tool`` / etc.).
    """
    # Late import: keep the SDK importable even if the native extension
    # is missing (test environments).
    try:
        from mcp_mesh_core import JobProxy as _JobProxy
    except Exception as e:
        logger.warning(
            "jobs_helper_tools: mcp_mesh_core.JobProxy unavailable (%s); "
            "helper tools will be no-ops",
            e,
        )
        _JobProxy = None  # type: ignore[assignment]

    async def __mesh_job_status(job_id: str) -> dict[str, Any]:
        """Return the latest registry-side state for ``job_id``.

        Single ``GET /jobs/{id}`` round-trip. Returns the full job row
        as a dict (status, progress, message, attempt count, etc.).
        Reading is unauthenticated by design — knowledge of the job_id
        is the capability (presigned-URL semantics, ~122-bit UUID).
        """
        if _JobProxy is None:
            raise RuntimeError(
                "__mesh_job_status: mcp_mesh_core.JobProxy unavailable"
            )
        proxy = _JobProxy(job_id, registry_url)
        return await proxy.status()

    async def __mesh_job_result(job_id: str) -> dict[str, Any]:
        """Return the terminal result for ``job_id`` if completed.

        Same wire as ``__mesh_job_status`` (registry returns the full
        row); this helper is a convenience that pulls out just the
        ``result`` payload + status. If the job hasn't reached a
        terminal state, the caller can re-poll ``__mesh_job_status``
        until ``status`` is ``completed`` / ``failed`` / ``cancelled``.
        """
        if _JobProxy is None:
            raise RuntimeError(
                "__mesh_job_result: mcp_mesh_core.JobProxy unavailable"
            )
        proxy = _JobProxy(job_id, registry_url)
        snapshot = await proxy.status()
        return {
            "status": snapshot.get("status"),
            "result": snapshot.get("result"),
            "error": snapshot.get("error"),
        }

    async def __mesh_job_cancel(
        job_id: str, reason: Optional[str] = None
    ) -> dict[str, Any]:
        """Request cancellation for ``job_id``. The registry forwards
        the signal to the owner replica when alive.

        Returns ``{"ok": True}`` once the registry has acknowledged.
        Idempotent: cancelling an already-terminal job is a no-op
        (registry returns success).
        """
        if _JobProxy is None:
            raise RuntimeError(
                "__mesh_job_cancel: mcp_mesh_core.JobProxy unavailable"
            )
        proxy = _JobProxy(job_id, registry_url)
        await proxy.cancel(reason)
        return {"ok": True, "job_id": job_id}

    return {
        _TOOL_NAME_STATUS: __mesh_job_status,
        _TOOL_NAME_RESULT: __mesh_job_result,
        _TOOL_NAME_CANCEL: __mesh_job_cancel,
    }


def _register_on_fastmcp(server: Any, helpers: dict[str, Any]) -> int:
    """Register the helper functions on a FastMCP server instance.

    Uses ``server.tool(name=..., description=...)`` (the decorator) since
    that's the most stable surface across FastMCP versions. Returns the
    number of helpers successfully registered.
    """
    descriptions = {
        _TOOL_NAME_STATUS: (
            "[Framework] Return the latest mesh-registry state for a job_id. "
            "Reads terminate at the registry; safe to call from any agent."
        ),
        _TOOL_NAME_RESULT: (
            "[Framework] Return the terminal result/status/error for a job_id "
            "via a single registry read."
        ),
        _TOOL_NAME_CANCEL: (
            "[Framework] Request cancellation for a job_id. The registry "
            "forwards the signal to the owner replica when alive."
        ),
    }
    registered = 0
    for tool_name, fn in helpers.items():
        try:
            decorator = server.tool(
                name=tool_name, description=descriptions.get(tool_name, "")
            )
            decorator(fn)
            registered += 1
            logger.debug("jobs_helper_tools: registered %s on %r", tool_name, server)
        except Exception as e:
            logger.warning(
                "jobs_helper_tools: failed to register %s on %r: %s",
                tool_name,
                server,
                e,
            )
    return registered


class JobsHelperToolsStep(PipelineStep):
    """Register ``__mesh_job_status`` / ``__mesh_job_result`` /
    ``__mesh_job_cancel`` on each discovered FastMCP server.

    Runs AFTER :class:`FastMCPServerDiscoveryStep` (so we know which
    servers exist) and BEFORE :class:`FastAPIServerSetupStep` (so the
    mounted FastMCP app advertises the helpers via ``tools/list``).

    Skipped when no ``MCP_MESH_REGISTRY_URL`` is configured — without a
    registry to talk to, the helpers can't function. Skipped gracefully
    when no FastMCP servers are discovered (an agent with only
    ``@mesh.route``-style HTTP routes wouldn't have a server to attach
    to).
    """

    def __init__(self) -> None:
        super().__init__(
            name="jobs-helper-tools",
            required=False,  # Best-effort: failing here must not block startup.
            description=(
                "Register MeshJob helper tools (__mesh_job_status / "
                "__mesh_job_result / __mesh_job_cancel) on every FastMCP "
                "server"
            ),
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="MeshJob helper tools registration")

        registry_url = context.get("registry_url") or os.environ.get(
            "MCP_MESH_REGISTRY_URL"
        )
        if not registry_url:
            result.status = PipelineStatus.SKIPPED
            result.message = (
                "MeshJob helper tools skipped: no registry_url configured "
                "(MCP_MESH_REGISTRY_URL unset)"
            )
            self.logger.info("⚠️ %s", result.message)
            return result

        servers = context.get("fastmcp_servers", {}) or {}
        if not servers:
            result.status = PipelineStatus.SKIPPED
            result.message = "MeshJob helper tools skipped: no FastMCP servers discovered"
            self.logger.info("⚠️ %s", result.message)
            return result

        helpers = _make_helper_tools(registry_url)
        total_registered = 0
        for server_key, server_instance in servers.items():
            n = _register_on_fastmcp(server_instance, helpers)
            total_registered += n
            self.logger.debug(
                "jobs_helper_tools: registered %d helpers on FastMCP server %r",
                n,
                server_key,
            )

        # Phase 1 MeshJob substrate (#bug 5): also register the helpers
        # in the DecoratorRegistry as mesh tools so they appear as
        # capabilities in the registry's catalog. Without this step the
        # helpers are only visible via FastMCP's local ``tools/list`` —
        # ``meshctl call <agent> __mesh_job_status ...`` would fail with
        # "tool not found" because the registry doesn't know they exist.
        self._register_helpers_in_decorator_registry(helpers)

        result.message = (
            f"Registered {total_registered} MeshJob helper tools across "
            f"{len(servers)} FastMCP server(s)"
        )
        self.logger.info("📨 %s", result.message)
        return result

    def _register_helpers_in_decorator_registry(
        self, helpers: dict[str, Any]
    ) -> None:
        """Publish each helper as a ``@mesh.tool`` entry so the heartbeat
        preparation step picks them up as capabilities the registry
        knows about (#bug 5).

        Helpers are framework primitives — auto-registered on every mesh
        agent, no user-declared dependencies, capability name == tool
        name. Using the same registration path that user tools use
        guarantees the heartbeat / catalog wire shape stays consistent.
        """
        try:
            from ...engine.decorator_registry import DecoratorRegistry
        except Exception as e:
            self.logger.warning(
                "jobs_helper_tools: could not import DecoratorRegistry "
                "(%s); helpers will not be in the registry catalog",
                e,
            )
            return

        descriptions = {
            "__mesh_job_status": (
                "[Framework] Return the latest mesh-registry state for "
                "a job_id. Reads terminate at the registry; safe to call "
                "from any agent."
            ),
            "__mesh_job_result": (
                "[Framework] Return the terminal result/status/error "
                "for a job_id via a single registry read."
            ),
            "__mesh_job_cancel": (
                "[Framework] Request cancellation for a job_id. The "
                "registry forwards the signal to the owner replica when "
                "alive."
            ),
        }

        for tool_name, fn in helpers.items():
            metadata = {
                "capability": tool_name,
                "function_name": tool_name,
                "version": "1.0.0",
                "tags": ["mesh-jobs", "framework"],
                "description": descriptions.get(tool_name, ""),
                "dependencies": [],
                # Mark as framework-internal so future filters can
                # distinguish helper tools from user-declared tools.
                "framework_internal": True,
            }
            try:
                DecoratorRegistry.register_mesh_tool(fn, metadata)
                self.logger.debug(
                    "jobs_helper_tools: registered %s in DecoratorRegistry",
                    tool_name,
                )
            except Exception as e:
                self.logger.warning(
                    "jobs_helper_tools: failed to register %s in "
                    "DecoratorRegistry: %s",
                    tool_name,
                    e,
                )

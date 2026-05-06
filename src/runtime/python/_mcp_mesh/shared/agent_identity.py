"""Centralized agent identity resolution for MCP Mesh runtime.

Returns the stable per-process agent identifier used to:

* Stamp ``owner_instance_id`` on claimed jobs (claim worker → ``POST /jobs/claim``).
* Stamp ``instance_id`` on job-batch deltas (JobController → ``POST /jobs/batch``).
* Identify the agent in heartbeats, registrations, and job submissions.

These three callers MUST resolve to the same value; otherwise the registry
rejects delta posts as ``not_owner`` (the claim's owner_instance_id won't
match the batch's instance_id) and progress / terminal updates silently
drop. See ``MESHJOB_DESIGN.org`` "Producer-side flow / Tick step".

Resolution order
----------------

1. ``MCP_MESH_AGENT_ID`` env var (explicit override — production K8s
   sets this to the pod name).
2. ``MCP_MESH_AGENT_NAME`` env var (legacy alias, kept for backwards
   compatibility — agents that set NAME but not ID still work).
3. The resolved agent_id from
   :class:`_mcp_mesh.engine.decorator_registry.DecoratorRegistry` —
   this is the synthetic ``{prefix}-{8chars}`` value the startup
   pipeline generated and persisted in the pipeline context. Both the
   claim worker and the heartbeat publisher use this same value, so
   making the JobController construction read from here too closes the
   instance_id mismatch loop.
4. ``HOSTNAME`` env var (Docker / Linux pods set this).
5. ``socket.gethostname()`` (works on bare macOS / Windows where
   ``HOSTNAME`` is not exported by the shell).

The ``socket.gethostname()`` fallback is the cross-platform last-ditch
that keeps the runtime working in plain ``python3 main.py`` invocations
on macOS — without it, the JobController falls back to a regular call
and progress deltas never reach the registry.
"""

from __future__ import annotations

import logging
import os
import socket
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_agent_id() -> Optional[str]:
    """Resolve the stable agent identifier for this process.

    Returns ``None`` only when every source fails — including
    ``socket.gethostname()`` which essentially never raises. Callers
    should treat ``None`` as "agent identity unavailable" and degrade
    gracefully (e.g. fall back to a non-job dispatch path).
    """
    # 1) Explicit env override.
    explicit = os.environ.get("MCP_MESH_AGENT_ID")
    if explicit:
        return explicit

    # 2) Legacy NAME alias (some deployments set this instead).
    legacy = os.environ.get("MCP_MESH_AGENT_NAME")
    if legacy:
        return legacy

    # 3) Resolved decorator-registry config — same value the claim
    # worker uses (passed via pipeline context as ``agent_id``).
    try:
        from ..engine.decorator_registry import DecoratorRegistry

        config = DecoratorRegistry.get_resolved_agent_config()
        agent_id = config.get("agent_id") if isinstance(config, dict) else None
        if agent_id and agent_id != "unknown":
            return agent_id
    except Exception as e:
        # Decorator registry may not be importable in tightly mocked
        # tests; fall through to hostname-based fallback.
        logger.debug("resolve_agent_id: decorator registry unavailable (%s)", e)

    # 4) Container-style HOSTNAME (Docker, K8s).
    hostname_env = os.environ.get("HOSTNAME")
    if hostname_env:
        return hostname_env

    # 5) Cross-platform fallback — bare macOS / Windows shells don't
    # export HOSTNAME but ``socket.gethostname()`` always returns
    # something usable.
    try:
        return socket.gethostname() or None
    except Exception as e:
        logger.debug("resolve_agent_id: socket.gethostname failed (%s)", e)
        return None

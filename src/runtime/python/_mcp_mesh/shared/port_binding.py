"""
Pre-bind socket helper enforcing the bound-port == registered-port invariant.

Issue #1194: when an agent's configured HTTP port was already in use, the
bind error was raised inside a background thread and swallowed — the agent
then registered the *configured* port with the registry even though nothing
was listening on it (a phantom endpoint). Consumers resolved dependencies to
an endpoint owned by a different process, or by nobody.

The fix is "adapt, don't crash": bind the server socket explicitly BEFORE
registration so bind failures are synchronous, and hand the already-bound
socket to uvicorn (``uvicorn.Server.run(sockets=...)``). On a port conflict
we fall back to an OS-assigned port (bind 0) with a prominent warning, and
the ACTUAL bound port is what flows into registration — the same path the
explicit ``http_port=0`` configuration uses.

Invariant: no runtime may ever register a port it did not bind.
"""

import logging
import socket

logger = logging.getLogger(__name__)

# Default budget for waiting on proven-serving after the socket binds.
# Sized for slow-but-healthy ASGI lifespans (model loading, connection-pool
# warmup, schema migration checks) — NOT for the bind itself, which is
# synchronous and already enforced by bind_server_socket_with_fallback.
SERVER_STARTUP_TIMEOUT_DEFAULT_SECONDS = 30.0


def get_server_startup_timeout() -> float:
    """Budget (seconds) for waiting on a server to prove it is serving.

    Configurable via ``MCP_MESH_SERVER_STARTUP_TIMEOUT`` (float seconds,
    default 30). Two consumers share this budget:

    * ``mesh.decorators._start_uvicorn_immediately`` — how long the
      decorator waits for ``uvicorn.Server.started`` before declaring the
      record "starting" (bound, not yet proven) and moving on.
    * ``startup_orchestrator._setup_heartbeat_background`` — how long the
      heartbeat defers its FIRST registration on the started-signal.

    This is a *liveness deferral*, not a separate invariant: the hard
    invariant stays bind-level (never register a port this process did not
    bind). Expiry never fails startup — the port is genuinely held, so
    registration proceeds; a server that ultimately cannot serve kills the
    process (and with it the heartbeat), making a too-early registration
    transient at worst.
    """
    from .config_resolver import ValidationRule, get_config_value

    value = get_config_value(
        "MCP_MESH_SERVER_STARTUP_TIMEOUT",
        default=SERVER_STARTUP_TIMEOUT_DEFAULT_SECONDS,
        rule=ValidationRule.FLOAT_RULE,
    )
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return SERVER_STARTUP_TIMEOUT_DEFAULT_SECONDS
    if timeout <= 0:
        logger.warning(
            "MCP_MESH_SERVER_STARTUP_TIMEOUT must be > 0 (got %s); "
            "using default %.0fs",
            value,
            SERVER_STARTUP_TIMEOUT_DEFAULT_SECONDS,
        )
        return SERVER_STARTUP_TIMEOUT_DEFAULT_SECONDS
    return timeout


def _bind(host: str, port: int) -> socket.socket:
    """Bind a TCP server socket to (host, port); close the socket on failure.

    Mirrors uvicorn's ``Config.bind_socket`` socket options (SO_REUSEADDR,
    inheritable) so handing the socket to uvicorn behaves identically to
    uvicorn binding it itself.
    """
    family = socket.AF_INET6 if ":" in (host or "") else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(True)
    return sock


def bind_server_socket_with_fallback(
    host: str, port: int
) -> tuple[socket.socket, int]:
    """Bind a server socket, falling back to an OS-assigned port on conflict.

    Args:
        host: Bind host (e.g. "0.0.0.0").
        port: Configured port. 0 means auto-assign (no fallback semantics —
            the OS picks a free port directly).

    Returns:
        ``(sock, actual_port)``. The socket is bound but NOT listening —
        uvicorn calls ``listen()`` itself when given a pre-bound socket.
        Until then, connection attempts against the port are REFUSED, not
        queued (a listen backlog only exists after ``listen()``).
        ``actual_port`` is read back from the socket, so it is always the
        port the process actually owns.

    Raises:
        OSError: if even the port-0 bind fails (nothing to adapt to).
    """
    try:
        sock = _bind(host, port)
    except OSError as e:
        if port == 0:
            raise
        logger.warning(
            "⚠️ PORT CONFLICT: configured HTTP port %d on %s is unavailable "
            "(%s). Falling back to an OS-assigned port so the agent can "
            "still serve — the registry will be given the ACTUAL bound "
            "port, not the configured one. Another process likely owns "
            "port %d; fix the port assignment to silence this warning.",
            port,
            host,
            e,
            port,
        )
        sock = _bind(host, 0)

    actual_port = sock.getsockname()[1]
    return sock, actual_port

"""
Regression tests for issue #1312.

FastMCP enables DNS-rebinding Host/Origin validation by default
(``http_host_origin_protection = True``), whose allowed-hosts list is
localhost-only. In Kubernetes every ``/mcp`` call arrives with a ``Host``
header set to the Service DNS name (e.g. ``my-agent.default:8080``), which is
not localhost, so the guard rejects it with ``421 Misdirected Request``.

Mesh is an internal service mesh — the browser DNS-rebinding threat model does
not apply — so it builds every served FastMCP app with
``host_origin_protection=False``. These tests guard that override:

* behavioral: a served app with the override accepts a non-localhost Host,
  while the same app with protection left on returns 421 (proving the fix
  matters). Skipped on FastMCP versions whose ``http_app`` predates the
  ``host_origin_protection`` kwarg.
* structural: ``HttpMcpWrapper`` actually passes ``host_origin_protection=False``
  to ``http_app`` — meaningful on any FastMCP version, so it still guards the
  wiring even before the version pin takes effect.
"""

import inspect

import pytest

FOREIGN_HOST = "some-service.namespace:8080"

_HTTP_APP_ACCEPTS_OVERRIDE = "host_origin_protection" in inspect.signature(
    __import__("fastmcp").FastMCP.http_app
).parameters


def _build_app(protection):
    """Build a served mesh-style streamable-HTTP app."""
    from fastmcp import FastMCP

    server = FastMCP("test-1312")

    @server.tool
    def ping() -> str:
        return "pong"

    kwargs = {"stateless_http": True, "transport": "streamable-http"}
    if protection is not None:
        kwargs["host_origin_protection"] = protection
    return server.http_app(**kwargs)


def _post_initialize(app, host):
    from starlette.testclient import TestClient

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "c", "version": "1"},
        },
    }
    headers = {
        "Host": host,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app) as client:
        return client.post("/mcp/", json=body, headers=headers)


@pytest.mark.skipif(
    not _HTTP_APP_ACCEPTS_OVERRIDE,
    reason="installed FastMCP predates host_origin_protection kwarg",
)
def test_1312_override_accepts_foreign_host():
    """With the override, a non-localhost (k8s Service-DNS) Host is NOT 421."""
    resp = _post_initialize(_build_app(protection=False), FOREIGN_HOST)
    assert resp.status_code != 421, resp.text
    assert resp.status_code == 200, resp.text


@pytest.mark.skipif(
    not _HTTP_APP_ACCEPTS_OVERRIDE,
    reason="installed FastMCP predates host_origin_protection kwarg",
)
def test_1312_default_protection_rejects_foreign_host():
    """Without the override the guard rejects the same Host with 421.

    Demonstrates the regression the override fixes.
    """
    resp = _post_initialize(_build_app(protection=None), FOREIGN_HOST)
    assert resp.status_code == 421, resp.text


def test_1312_http_wrapper_passes_override():
    """Structural guard (version-independent): HttpMcpWrapper must call
    http_app with host_origin_protection=False."""
    from unittest.mock import MagicMock

    from _mcp_mesh.engine.http_wrapper import HttpMcpWrapper

    mock_server = MagicMock()
    mock_server.http_app.return_value = MagicMock()

    HttpMcpWrapper(mock_server)

    mock_server.http_app.assert_called_once()
    assert mock_server.http_app.call_args.kwargs.get("host_origin_protection") is False

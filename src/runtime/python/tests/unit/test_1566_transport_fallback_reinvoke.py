"""Unit tests for issue #1566: transport-failure fallback re-invokes the tool.

``UnifiedMCPProxy.call_tool`` runs a direct HTTP POST as its PRIMARY transport
and retries through the FastMCP client when that fails. The retry used to be
gated on a *substring* check ("Tool call error" / "JSON-RPC error"), while
``_http_call`` flattened every transport failure into a generic
``RuntimeError`` whose message contained neither string. So a read timeout or
an HTTP 500 — both of which mean the provider received the request and very
likely ran the tool — took the fallback and invoked the provider a SECOND
time, and the caller saw one success.

#1278 already fixed exactly this hazard for one error type
(``SupersededError``), with the comment "which would invoke the provider a
SECOND time". These tests pin the generalisation: the fallback fires only for
``RequestNotSentError``, which ``_http_call`` raises only when the request
provably never left this process.

The httpx class hierarchy is the trap. ``ConnectTimeout`` and ``PoolTimeout``
are subclasses of ``TimeoutException`` but are sent-safe, while ``ReadTimeout``
is its sibling and is not — so neither "retry all timeouts" nor "retry no
timeouts" is correct.
"""

import asyncio
import builtins
import inspect
import json
import weakref
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from _mcp_mesh.engine.superseded import SupersededError
from _mcp_mesh.engine.unified_mcp_proxy import (
    RequestNotSentError,
    UnifiedMCPProxy,
)


class _FakeHttpResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Server error '{self.status_code}'",
                request=httpx.Request("POST", "http://provider:8080/mcp"),
                response=httpx.Response(self.status_code, text=self.text),
            )


class _RaisingHttpxClient:
    """PRIMARY transport that fails a given way, counting real POST attempts."""

    def __init__(self, exc=None, response=None):
        self._exc = exc
        self._response = response
        self.post_calls = 0
        self.timeouts: list = []

    async def post(self, url, content=None, headers=None, timeout=None):
        self.post_calls += 1
        self.timeouts.append(timeout)
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeFastMCPClient:
    """FALLBACK transport. Counts tool calls; records the timeout it got."""

    def __init__(self):
        self.call_count = 0
        self.timeouts: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, arguments=None, **kwargs):
        self.call_count += 1
        self.timeouts.append(kwargs.get("timeout"))
        return {"content": [{"type": "text", "text": "fallback-result"}]}


def _request():
    return httpx.Request("POST", "http://provider:8080/mcp")


def _run_call(proxy, primary, fastmcp_client=None):
    """Drive ``call_tool`` with both transports stubbed."""
    factory = AsyncMock(return_value=fastmcp_client) if fastmcp_client else AsyncMock()
    with (
        patch(
            "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
            return_value=primary,
        ),
        patch.object(proxy, "_get_or_create_fastmcp_client", factory),
    ):
        try:
            return asyncio.run(proxy.call_tool("charge_card", {"amount": 10})), None
        except Exception as e:  # noqa: BLE001 - the assertion subject
            return None, e
    return None, None


# Transport failures that mean the provider MAY HAVE run the tool. Retrying any
# of these is a silent double execution of a non-idempotent tool.
NOT_SENT_SAFE = [
    pytest.param(
        httpx.ReadTimeout("timed out", request=_request()),
        id="ReadTimeout-request-was-sent",
    ),
    pytest.param(
        httpx.WriteTimeout("timed out", request=_request()),
        id="WriteTimeout-partial-send-ambiguous",
    ),
    pytest.param(
        httpx.ReadError("connection reset", request=_request()),
        id="ReadError-broke-after-connect",
    ),
    pytest.param(
        httpx.WriteError("broken pipe", request=_request()),
        id="WriteError-broke-mid-send",
    ),
    pytest.param(
        httpx.RemoteProtocolError("server disconnected", request=_request()),
        id="RemoteProtocolError-server-spoke",
    ),
    pytest.param(
        httpx.DecodingError("bad encoding", request=_request()),
        id="DecodingError-response-received",
    ),
]

# Failures that provably happened BEFORE the request left this process.
SENT_SAFE = [
    pytest.param(
        httpx.ConnectTimeout("connect timed out", request=_request()),
        id="ConnectTimeout-subclass-of-TimeoutException",
    ),
    pytest.param(
        httpx.PoolTimeout("no free connection", request=_request()),
        id="PoolTimeout-subclass-of-TimeoutException",
    ),
    pytest.param(
        httpx.ConnectError("connection refused", request=_request()),
        id="ConnectError-refused-dns-tls",
    ),
    pytest.param(
        httpx.ProxyError("tunnel refused", request=_request()),
        id="ProxyError-no-tunnel",
    ),
]


class TestHttpxHierarchyAssumptions:
    """The classification is only correct if httpx still nests these this way."""

    def test_connect_and_pool_timeouts_are_timeout_exceptions(self):
        assert issubclass(httpx.ConnectTimeout, httpx.TimeoutException)
        assert issubclass(httpx.PoolTimeout, httpx.TimeoutException)

    def test_read_and_write_timeouts_are_siblings_not_parents(self):
        assert issubclass(httpx.ReadTimeout, httpx.TimeoutException)
        assert issubclass(httpx.WriteTimeout, httpx.TimeoutException)
        assert not issubclass(httpx.ReadTimeout, httpx.ConnectTimeout)

    def test_connect_error_is_a_network_error_not_a_timeout(self):
        assert issubclass(httpx.ConnectError, httpx.NetworkError)
        assert not issubclass(httpx.ConnectError, httpx.TimeoutException)
        # ReadError shares the NetworkError base, so "retry all NetworkError"
        # would also be wrong.
        assert issubclass(httpx.ReadError, httpx.NetworkError)


class TestNoFallbackAfterTheRequestWasSent:
    @pytest.mark.parametrize("exc", NOT_SENT_SAFE)
    def test_single_invocation_and_error_surfaced(self, exc):
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        primary = _RaisingHttpxClient(exc=exc)
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert result is None, f"{type(exc).__name__} must not be retried into a result"
        assert isinstance(err, RuntimeError)
        assert not isinstance(err, RequestNotSentError)
        # Exactly ONE tools/call reached the provider.
        assert primary.post_calls == 1
        assert fallback.call_count == 0

    def test_http_500_does_not_retry(self):
        # The provider definitively ran the tool and responded.
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        primary = _RaisingHttpxClient(
            response=_FakeHttpResponse("boom", status_code=500)
        )
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert result is None
        assert "HTTP error 500" in str(err)
        assert primary.post_calls == 1
        assert fallback.call_count == 0

    def test_jsonrpc_error_does_not_retry(self):
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        rpc = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "tool blew up"},
            }
        )
        primary = _RaisingHttpxClient(response=_FakeHttpResponse(rpc))
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert result is None
        assert "tool blew up" in str(err)
        assert primary.post_calls == 1
        assert fallback.call_count == 0

    def test_empty_response_does_not_retry(self):
        # The provider answered (with nothing); it ran.
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        primary = _RaisingHttpxClient(response=_FakeHttpResponse(""))
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert result is None
        assert "Empty response" in str(err)
        assert primary.post_calls == 1
        assert fallback.call_count == 0

    def test_superseded_still_typed_and_single_invoke(self):
        # #1278 regression guard: the special case must survive its
        # generalisation.
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        rpc = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": True,
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"error": "claim_superseded", "detail": "stale epoch"}
                            ),
                        }
                    ],
                },
            }
        )
        primary = _RaisingHttpxClient(response=_FakeHttpResponse(rpc))
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert isinstance(err, SupersededError)
        assert err.detail == "stale epoch"
        assert primary.post_calls == 1
        assert fallback.call_count == 0


class TestFallbackStillRunsWhenNothingWasSent:
    @pytest.mark.parametrize("exc", SENT_SAFE)
    def test_unreachable_endpoint_falls_back(self, exc):
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        primary = _RaisingHttpxClient(exc=exc)
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert err is None, f"{type(exc).__name__} should still fall back: {err}"
        assert result["content"][0]["text"] == "fallback-result"
        assert primary.post_calls == 1
        assert fallback.call_count == 1

    def test_fallback_inherits_the_primary_call_budget(self, monkeypatch):
        # The fallback used to run on the pooled client's 300s stream timeout,
        # so a tightened budget was silently abandoned.
        monkeypatch.setenv("MCP_MESH_CALL_TIMEOUT", "7")
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        primary = _RaisingHttpxClient(
            exc=httpx.ConnectError("refused", request=_request())
        )
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert err is None
        assert fallback.timeouts == [7]

    def test_both_transports_failing_reports_both(self):
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        primary = _RaisingHttpxClient(
            exc=httpx.ConnectError("refused", request=_request())
        )

        class _BrokenFallback(_FakeFastMCPClient):
            async def call_tool(self, name, arguments=None, **kwargs):
                self.call_count += 1
                raise RuntimeError("fallback down too")

        result, err = _run_call(proxy, primary, _BrokenFallback())

        assert result is None
        assert "HTTP=" in str(err) and "FastMCP=" in str(err)


class TestDecodeTimeImportErrorIsNotUnsent:
    """httpx's BrotliDecoder / ZStandardDecoder raise a BARE ImportError while
    READING a response whose Content-Encoding is br/zstd without the optional
    package. An ``except ImportError`` wrapped around the whole call body would
    classify that as "request never sent" and double-invoke — through the arm
    documented as proven-safe."""

    def test_httpx_decoders_really_raise_bare_importerror(self):
        import httpx._decoders as decoders

        source = inspect.getsource(decoders)
        assert "raise ImportError(" in source
        # ...and they are constructed at response-read time, not import time.
        assert "class BrotliDecoder" in source
        assert "class ZStandardDecoder" in source

    def test_decode_time_importerror_does_not_fall_back(self):
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        primary = _RaisingHttpxClient(
            exc=ImportError(
                "Using 'BrotliDecoder', but neither of the 'brotlicffi' or "
                "'brotli' libraries are installed."
            )
        )
        fallback = _FakeFastMCPClient()

        result, err = _run_call(proxy, primary, fallback)

        assert result is None
        assert not isinstance(err, RequestNotSentError)
        assert primary.post_calls == 1
        assert fallback.call_count == 0

    def test_a_genuinely_missing_httpx_is_still_unsent(self):
        # The import itself IS unsent — that classification must survive.
        from unittest.mock import AsyncMock, patch

        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("No module named 'httpx'")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", fake_import),
            patch.object(proxy, "_get_or_create_fastmcp_client", AsyncMock()),
        ):
            with pytest.raises(RequestNotSentError):
                asyncio.run(proxy._http_call("charge_card", {}))


class TestFallbackTransportBudget:
    """The fallback's per-call timeout is only real if the transport underneath
    it is willing to wait that long: ``stream_timeout`` becomes the httpx read
    timeout at construction and is ignored on a pool cache hit, so a bigger
    budget was silently clipped back to the pooled client's."""

    def test_pool_key_includes_the_stream_timeout(self):
        from _mcp_mesh.engine import unified_mcp_proxy as ump

        seen: list = []

        async def go():
            with patch.object(
                UnifiedMCPProxy,
                "_build_fastmcp_client",
                staticmethod(lambda *a, **k: object()),
            ):
                await UnifiedMCPProxy._get_or_create_fastmcp_client(
                    "http://p:8080/mcp", "http://p:8080", 300
                )
                await UnifiedMCPProxy._get_or_create_fastmcp_client(
                    "http://p:8080/mcp", "http://p:8080", 900
                )
                with ump._pool_lock:
                    seen.extend(ump._fastmcp_client_pool)

        try:
            asyncio.run(go())
            budgets = sorted(k[2] for k in seen)
            assert budgets == [300, 900], (
                "a larger budget reused the tighter pooled client"
            )
        finally:
            with ump._pool_lock:
                ump._fastmcp_client_pool.clear()
                ump._pool_loops.clear()

    def test_fallback_requests_a_transport_budget_at_least_the_call_budget(
        self, monkeypatch
    ):
        monkeypatch.setenv("MCP_MESH_CALL_TIMEOUT", "900")
        proxy = UnifiedMCPProxy("http://provider:8080", "charge_card")
        assert proxy.stream_timeout == 300  # the default that used to clip

        primary = _RaisingHttpxClient(
            exc=httpx.ConnectError("refused", request=_request())
        )
        fallback = _FakeFastMCPClient()
        factory = AsyncMock(return_value=fallback)

        with (
            patch(
                "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
                return_value=primary,
            ),
            patch.object(proxy, "_get_or_create_fastmcp_client", factory),
        ):
            asyncio.run(proxy.call_tool("charge_card", {}))

        requested_stream_timeout = factory.await_args.args[2]
        assert requested_stream_timeout >= 900
        assert fallback.timeouts == [900]


class TestPoolOwnerRegistration:
    def test_pool_loops_holds_weak_references(self):
        from _mcp_mesh.engine import unified_mcp_proxy as ump

        # A strong map would keep every loop this process ever called out on
        # alive until close_connection_pools ran.
        assert isinstance(ump._pool_loops, weakref.WeakValueDictionary)

    def test_owner_is_registered_before_the_client_is_published(self):
        from _mcp_mesh.engine import unified_mcp_proxy as ump

        # Both happen under _pool_lock, so close_connection_pools can never
        # snapshot a client whose owner is unknown and drop it un-closed.
        source = inspect.getsource(ump._get_httpx_client_sync)
        reg = source.index("_pool_loops[id(loop)] = loop")
        pub = source.index("_httpx_pool[key] = client")
        lock = source.index("with _pool_lock:")
        assert lock < reg < pub


class TestRequestNotSentErrorContract:
    def test_is_a_runtime_error_for_existing_callers(self):
        assert issubclass(RequestNotSentError, RuntimeError)

    def test_carries_the_resolved_budget(self):
        err = RequestNotSentError("nope", timeout_secs=42)
        assert err.timeout_secs == 42

    def test_budget_is_optional(self):
        assert RequestNotSentError("nope").timeout_secs is None

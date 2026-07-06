"""Unit tests for issue #1278: typed supersession signal.

A provider tool that detects it is being called by a SUPERSEDED executor (the
app compares the calling job's epoch via ``mesh.calling_job()`` — issue #1263)
rejects the call by raising a typed ``mesh.SupersededError``. That crosses the
wire as the reserved ``{"error":"claim_superseded"}`` app envelope (plus an
optional ``"detail"``), and the CALLING side's injected ``McpMeshTool`` proxy
recognizes the envelope and re-raises ``mesh.SupersededError`` — so a superseded
caller unwinds with one ``except mesh.SupersededError`` instead of
string-matching ``claim_superseded`` after every mutating call.

Structural parallel of the ``dependency_unavailable`` refusal (issue #1273):
both raise a ``ToolError`` whose message is a reserved JSON envelope, so the
contract (not the carrier) drives classification. Mirrors
``test_1273_direct_invoke_required.py``.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import mesh
import pytest
from _mcp_mesh.engine.superseded import (
    CLAIM_SUPERSEDED_MARKER,
    SupersededError,
    parse_superseded_envelope,
)
from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError


class _FakeContent:
    def __init__(self, text):
        self.text = text


class _FakeErrorResult:
    """Minimal stand-in for a FastMCP ``CallToolResult`` with ``isError``."""

    def __init__(self, text):
        self.isError = True
        self.content = [_FakeContent(text)]


class TestSupersededErrorClass:
    def test_marker_matches_job_path_string(self):
        # The reserved marker is the SAME canonical string the job path uses on
        # the wire (Rust task_backend.rs CLAIM_SUPERSEDED_REASON / Go).
        assert CLAIM_SUPERSEDED_MARKER == "claim_superseded"

    def test_is_toolerror_subclass(self):
        assert issubclass(SupersededError, ToolError)
        assert isinstance(SupersededError("x"), ToolError)

    def test_serialized_envelope_with_detail(self):
        err = SupersededError("stale epoch 3")
        assert json.loads(str(err)) == {
            "error": "claim_superseded",
            "detail": "stale epoch 3",
        }
        assert err.detail == "stale epoch 3"

    def test_serialized_envelope_omits_detail_when_none(self):
        err = SupersededError()
        # detail key omitted entirely (not a null) when no detail supplied.
        assert json.loads(str(err)) == {"error": "claim_superseded"}
        assert err.detail is None

    def test_public_export_is_same_class(self):
        assert mesh.SupersededError is SupersededError


class TestProviderEmit:
    """Raising ``mesh.SupersededError`` from a real @mesh tool auto-emits an
    isError tool result carrying the reserved envelope — through the EXISTING
    fastmcp ToolError path, no provider wrapper change."""

    def test_raise_produces_iserror_reserved_envelope(self):
        srv = FastMCP(name="provider")

        @srv.tool()
        def mutate():
            raise mesh.SupersededError("stale epoch 3")

        async def go():
            async with Client(srv) as c:
                return await c.call_tool("mutate", {}, raise_on_error=False)

        res = asyncio.run(go())
        assert res.is_error
        assert json.loads(res.content[0].text) == {
            "error": "claim_superseded",
            "detail": "stale epoch 3",
        }

    def test_raise_without_detail_emits_envelope_without_detail(self):
        srv = FastMCP(name="provider")

        @srv.tool()
        def mutate():
            raise mesh.SupersededError()

        async def go():
            async with Client(srv) as c:
                return await c.call_tool("mutate", {}, raise_on_error=False)

        res = asyncio.run(go())
        assert res.is_error
        assert json.loads(res.content[0].text) == {"error": "claim_superseded"}


class TestParseSupersededEnvelope:
    """The shared recognizer both proxy sites delegate to."""

    def test_recognizes_marker(self):
        err = parse_superseded_envelope('{"error":"claim_superseded"}')
        assert isinstance(err, SupersededError)
        assert err.detail is None

    def test_carries_detail(self):
        err = parse_superseded_envelope('{"error":"claim_superseded","detail":"x"}')
        assert isinstance(err, SupersededError)
        assert err.detail == "x"

    def test_non_json_falls_through(self):
        assert parse_superseded_envelope("boom, plain text error") is None

    def test_dependency_unavailable_not_misclassified(self):
        # A sibling reserved envelope must NOT trip the supersession recognizer.
        assert (
            parse_superseded_envelope(
                '{"error":"dependency_unavailable","capability":"lookup"}'
            )
            is None
        )

    def test_json_non_object_falls_through(self):
        assert parse_superseded_envelope('"claim_superseded"') is None
        assert parse_superseded_envelope("[1,2,3]") is None

    def test_non_string_detail_dropped(self):
        err = parse_superseded_envelope('{"error":"claim_superseded","detail":42}')
        assert isinstance(err, SupersededError)
        assert err.detail is None


class TestConsumerRecognizeMainPath:
    """The injected-proxy FastMCP error path (``_convert_mcp_result_to_python``,
    unified_mcp_proxy.py :843): an isError remote result carrying the reserved
    envelope re-raises ``mesh.SupersededError`` instead of the generic
    RuntimeError."""

    def _proxy(self):
        return UnifiedMCPProxy("http://provider:8080", "mutate")

    def test_superseded_iserror_raises_typed_error(self):
        proxy = self._proxy()
        result = _FakeErrorResult('{"error":"claim_superseded"}')
        with pytest.raises(SupersededError) as excinfo:
            proxy._convert_mcp_result_to_python(result)
        assert excinfo.value.detail is None

    def test_superseded_iserror_carries_detail(self):
        proxy = self._proxy()
        result = _FakeErrorResult('{"error":"claim_superseded","detail":"stale"}')
        with pytest.raises(SupersededError) as excinfo:
            proxy._convert_mcp_result_to_python(result)
        assert excinfo.value.detail == "stale"

    def test_non_superseded_iserror_raises_generic_runtime_error(self):
        proxy = self._proxy()
        result = _FakeErrorResult("some ordinary tool failure")
        with pytest.raises(RuntimeError) as excinfo:
            proxy._convert_mcp_result_to_python(result)
        assert not isinstance(excinfo.value, SupersededError)
        assert "Remote tool call failed" in str(excinfo.value)

    def test_dependency_unavailable_iserror_stays_generic(self):
        # SupersededError does NOT swallow a sibling reserved envelope.
        proxy = self._proxy()
        result = _FakeErrorResult(
            '{"error":"dependency_unavailable","capability":"lookup"}'
        )
        with pytest.raises(RuntimeError) as excinfo:
            proxy._convert_mcp_result_to_python(result)
        assert not isinstance(excinfo.value, SupersededError)


class _FakeHttpResponse:
    def __init__(self, text):
        self.text = text
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        return None


class _FakeHttpxClient:
    """Records how many times the PRIMARY transport actually POSTs."""

    def __init__(self, text):
        self._text = text
        self.post_calls = 0

    async def post(self, url, content=None, headers=None, timeout=None):
        self.post_calls += 1
        return _FakeHttpResponse(self._text)


def _rpc_iserror_envelope(detail=None):
    envelope = {"error": "claim_superseded"}
    if detail is not None:
        envelope["detail"] = detail
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "isError": True,
                "content": [
                    {"type": "text", "text": json.dumps(envelope)}
                ],
            },
        }
    )


class TestPrimaryTransportEndToEnd:
    """The LIVE path: ``call_tool`` → ``_http_call`` (PRIMARY transport). This
    is the site the direct-``_convert_mcp_result_to_python`` tests could not
    reach — before the guard fix, ``_http_call`` rewrapped the SupersededError
    into a generic ``RuntimeError('HTTP call failed')`` which ``call_tool``
    misread as a transport failure and RETRIED via the FastMCP fallback,
    invoking the provider a SECOND time and losing the typed error.
    """

    def test_primary_superseded_typed_and_single_invoke(self):
        proxy = UnifiedMCPProxy("http://provider:8080", "mutate")
        fake_client = _FakeHttpxClient(_rpc_iserror_envelope("stale epoch 3"))
        fastmcp_factory = AsyncMock()  # the FALLBACK path — must NOT be entered

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
            return_value=fake_client,
        ), patch.object(
            proxy, "_get_or_create_fastmcp_client", fastmcp_factory
        ):
            with pytest.raises(SupersededError) as excinfo:
                asyncio.run(proxy.call_tool("mutate", {}))

        # (a) typed error reaches the caller — NOT a generic RuntimeError
        assert excinfo.value.detail == "stale epoch 3"
        # (b) provider invoked exactly ONCE — no fallback double-invoke
        assert fake_client.post_calls == 1
        fastmcp_factory.assert_not_called()

    def test_primary_generic_iserror_still_raises_runtime_error(self):
        # A non-superseded application error is still surfaced as before, and
        # (per the existing "Tool call error" guard) does not trigger fallback.
        proxy = UnifiedMCPProxy("http://provider:8080", "mutate")
        rpc = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "ordinary failure"}],
                },
            }
        )
        fake_client = _FakeHttpxClient(rpc)
        fastmcp_factory = AsyncMock()

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
            return_value=fake_client,
        ), patch.object(
            proxy, "_get_or_create_fastmcp_client", fastmcp_factory
        ):
            with pytest.raises(RuntimeError) as excinfo:
                asyncio.run(proxy.call_tool("mutate", {}))

        assert not isinstance(excinfo.value, SupersededError)
        assert fake_client.post_calls == 1
        fastmcp_factory.assert_not_called()


class TestStreamSupersession:
    """A superseded STREAMING producer surfaces via ``await call_task`` as a
    fastmcp ToolError whose message is the reserved envelope; ``stream()``
    re-raises it typed so streaming callers get the same one-catch contract."""

    def test_stream_superseded_raises_typed(self):
        srv = FastMCP(name="stream-provider")

        @srv.tool()
        def produce():  # non-streaming producer that refuses as superseded
            raise mesh.SupersededError("stale stream epoch")

        proxy = UnifiedMCPProxy(
            "http://provider:8080", "produce", {"stream_type": "text"}
        )

        client_cm = Client(srv)

        async def fake_factory(*args, **kwargs):
            return client_cm

        async def drive():
            chunks = []
            async for chunk in proxy.stream("produce"):
                chunks.append(chunk)
            return chunks

        with patch.object(
            proxy, "_get_or_create_fastmcp_client", side_effect=fake_factory
        ):
            with pytest.raises(SupersededError) as excinfo:
                asyncio.run(drive())

        assert excinfo.value.detail == "stale stream epoch"

    def test_stream_generic_toolerror_propagates_unchanged(self):
        srv = FastMCP(name="stream-provider")

        @srv.tool()
        def produce():
            raise ToolError("ordinary stream failure")

        proxy = UnifiedMCPProxy(
            "http://provider:8080", "produce", {"stream_type": "text"}
        )
        client_cm = Client(srv)

        async def fake_factory(*args, **kwargs):
            return client_cm

        async def drive():
            async for _ in proxy.stream("produce"):
                pass

        with patch.object(
            proxy, "_get_or_create_fastmcp_client", side_effect=fake_factory
        ):
            with pytest.raises(ToolError) as excinfo:
                asyncio.run(drive())

        assert not isinstance(excinfo.value, SupersededError)

"""Native Gemini SDK adapter for the @mesh.llm_provider invocation layer.

Adapts ``google.genai.Client`` (the unified google-genai SDK) to the
_Response/_StreamChunk shape contract that mesh's agentic loop in
``mesh/helpers.py`` expects (mirrors litellm.completion()'s shape via
mesh_llm_agent._MockResponse, and matches the anthropic_native /
openai_native adapters introduced in PR 1 / PR 2 of issue #834).

Backend selection by model prefix:
  * ``gemini/<model>``    → ``genai.Client(api_key=...)`` (AI Studio backend)
  * ``vertex_ai/<model>`` → ``genai.Client(vertexai=True, project=..., location=...)``
                            (Vertex AI backend; reads GOOGLE_CLOUD_PROJECT
                            and GOOGLE_CLOUD_LOCATION env vars)

Wire-shape divergence from OpenAI/Anthropic is significant — see
``_extract_system_instruction``, ``_convert_messages_to_gemini``,
``_convert_tools``, and ``_translate_content_block_to_gemini`` for the
translation surface. Key transformations:
  * System message → top-level ``systemInstruction`` (NOT in contents).
  * Roles renamed: ``assistant`` → ``model``; tool result → ``user`` with a
    ``functionResponse`` part (and a back-reference to the function NAME,
    not its id — Gemini has no tool-call ids).
  * OpenAI tools list → single ``functionDeclarations`` wrapper.
  * tool_choice → ``toolConfig.functionCallingConfig`` enum (AUTO / ANY / NONE).
  * Multimodal blocks: data-URI → ``inlineData``; https URL → ``fileData``.

Tool calls have NO id field on Gemini — we synthesize ``gemini_call_<index>``
identifiers when adapting responses, and maintain a ``tool_call_id → name``
map (built from the preceding assistant turn's tool_calls) when converting
tool result messages back into Gemini's NAME-keyed ``functionResponse`` parts.

K8s secret rotation: ``genai.Client`` is constructed per-call (no caching of
the wrapper itself); the underlying ``httpx.AsyncClient`` connection pool IS
cached process-wide via ``_get_shared_httpx_client`` and forwarded through
``HttpOptions(httpx_async_client=...)`` so TLS handshakes are reused across
calls. The pool carries no credential state.

HINT-mode preservation: the existing ``GeminiHandler.prepare_request`` decides
whether to attach ``response_format`` (no tools present) vs. fall back to HINT
mode (tools + Pydantic output — Gemini API has a non-deterministic infinite-
tool-loop bug for that combo). The native adapter just executes whatever the
handler hands it; HINT-mode flow is identical between native and LiteLLM
paths.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Matches: data:<mime>;base64,<data>
_DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.+)$", re.DOTALL)

# Model prefixes that route through this adapter.
_GEMINI_PREFIX = "gemini/"
_VERTEX_PREFIX = "vertex_ai/"


# ---------------------------------------------------------------------------
# Shared httpx connection pool (issue #834 perf fix)
# ---------------------------------------------------------------------------
# A single ``httpx.AsyncClient`` is reused across all native Gemini calls in
# this process. ``google.genai.Client`` accepts a custom async httpx client
# via ``HttpOptions(httpx_async_client=...)`` and uses the supplied pool
# instead of constructing a fresh one per call. This eliminates ~150-300ms
# per-call TLS+H2 setup overhead vs. LiteLLM (which does its own pool reuse).
#
# K8s secret rotation still works because the api_key is read fresh per call
# by callers and forwarded to the per-call ``genai.Client`` wrapper — the
# pool itself carries no credential state, only TCP/TLS connections.
_CACHED_HTTPX_CLIENT: httpx.AsyncClient | None = None
# Guards lazy-init / rebuild of the shared httpx client. The pool itself is
# safe for concurrent use; the lock only protects the check-then-create race
# at construction. Cheap (uncontended after first call) and correct under
# threaded harnesses (tests, sync wrapper paths) that touch the cache.
_CACHED_HTTPX_CLIENT_LOCK = threading.Lock()


def _get_shared_httpx_client() -> httpx.AsyncClient:
    """Lazily construct (or rebuild if closed) the shared httpx client.

    Single connection pool shared across all native Gemini calls in this
    process. Per-call ``genai.Client`` wrappers reuse this pool —
    eliminating ~150-300ms per-call TLS+H2 setup overhead. K8s secret
    rotation still works: ``api_key`` is read fresh per call; the pool
    carries no credential state.
    """
    global _CACHED_HTTPX_CLIENT
    # Fast path — no lock when the cached client is healthy. The check is
    # benign-racy (worst case: two threads both observe None and both enter
    # the lock; the second one finds the cache populated under the lock and
    # returns early).
    if _CACHED_HTTPX_CLIENT is not None and not _CACHED_HTTPX_CLIENT.is_closed:
        return _CACHED_HTTPX_CLIENT
    with _CACHED_HTTPX_CLIENT_LOCK:
        if _CACHED_HTTPX_CLIENT is None or _CACHED_HTTPX_CLIENT.is_closed:
            _CACHED_HTTPX_CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,  # connection establishment
                    read=600.0,    # body read — LLM responses can be slow
                    write=30.0,    # request body write
                    pool=5.0,      # waiting for free connection from pool
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=100,
                    keepalive_expiry=30.0,
                ),
            )
        return _CACHED_HTTPX_CLIENT


def _reset_shared_httpx_client() -> None:
    """For tests — reset the cached client. NOT for production use."""
    global _CACHED_HTTPX_CLIENT
    with _CACHED_HTTPX_CLIENT_LOCK:
        _CACHED_HTTPX_CLIENT = None


# ---------------------------------------------------------------------------
# litellm-shaped response objects
# ---------------------------------------------------------------------------
# These mirror _MockResponse / _MockMessage / _MockChoice / _MockUsage in
# ``_mcp_mesh.engine.mesh_llm_agent`` (and the corresponding shapes in
# ``anthropic_native`` / ``openai_native``). Kept independent here so this
# module does not import from mesh_llm_agent (avoids circular imports through
# the provider_handlers package).


class _Function:
    __slots__ = ("name", "arguments")

    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    __slots__ = ("id", "type", "function")

    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.type = "function"
        self.function = _Function(name=name, arguments=arguments)


class _Message:
    __slots__ = ("content", "role", "tool_calls")

    def __init__(
        self,
        content: str | None,
        role: str = "assistant",
        tool_calls: list[_ToolCall] | None = None,
    ):
        self.content = content
        self.role = role
        self.tool_calls = tool_calls or None


class _Choice:
    __slots__ = ("message", "finish_reason", "index")

    def __init__(self, message: _Message, finish_reason: str = "stop"):
        self.message = message
        self.finish_reason = finish_reason
        self.index = 0


class _Usage:
    __slots__ = ("prompt_tokens", "completion_tokens", "total_tokens")

    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens or 0
        self.completion_tokens = completion_tokens or 0
        self.total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)


class _Response:
    __slots__ = ("choices", "usage", "model")

    def __init__(
        self,
        message: _Message,
        usage: _Usage | None,
        model: str | None,
        finish_reason: str = "stop",
    ):
        self.choices = [_Choice(message, finish_reason=finish_reason)]
        self.usage = usage
        self.model = model


# ---------------------------------------------------------------------------
# litellm-shaped streaming chunk objects
# ---------------------------------------------------------------------------


class _Delta:
    __slots__ = ("content", "tool_calls", "role")

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[Any] | None = None,
        role: str | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls
        self.role = role


class _StreamChoice:
    __slots__ = ("delta", "index", "finish_reason")

    def __init__(
        self,
        delta: _Delta,
        index: int = 0,
        finish_reason: str | None = None,
    ):
        self.delta = delta
        self.index = index
        self.finish_reason = finish_reason


class _StreamChunk:
    __slots__ = ("choices", "usage", "model")

    def __init__(
        self,
        delta: _Delta,
        usage: _Usage | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
    ):
        self.choices = [_StreamChoice(delta, finish_reason=finish_reason)]
        self.usage = usage
        self.model = model


class _StreamFunctionDelta:
    __slots__ = ("name", "arguments")

    def __init__(self, name: str | None = None, arguments: str | None = None):
        self.name = name
        self.arguments = arguments


class _StreamToolCallDelta:
    """Tool-call fragment matching litellm's streamed tool_call shape.

    ``MeshLlmAgent._merge_streamed_tool_calls`` reads ``index``, ``id``,
    ``type``, and ``function.name`` / ``function.arguments`` off these
    deltas. Gemini emits ``function_call`` parts as COMPLETE objects within
    a single chunk (no incremental argument streaming like OpenAI/Anthropic),
    so we always populate id+name+arguments together — the merger handles
    "everything in one fragment" cleanly because subsequent fragment lookups
    return None and the existing fields stay intact.
    """

    __slots__ = ("index", "id", "type", "function")

    def __init__(
        self,
        index: int,
        id: str | None = None,
        name: str | None = None,
        arguments: str | None = None,
    ):
        self.index = index
        self.id = id
        self.type = "function" if id is not None else None
        self.function = _StreamFunctionDelta(name=name, arguments=arguments)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_IS_AVAILABLE_CACHE: bool | None = None


def is_available() -> bool:
    """True if the ``google.genai`` SDK is importable in this process.

    Result is cached after the first probe — the SDK presence does not
    change at runtime, and the import-then-immediately-discard pattern
    showed up as needless overhead on the dispatch-decision hot path in
    PR 1 (anthropic_native) so the same caching is applied here.
    """
    global _IS_AVAILABLE_CACHE
    if _IS_AVAILABLE_CACHE is not None:
        return _IS_AVAILABLE_CACHE
    try:
        import google.genai  # noqa: F401
    except ImportError:
        _IS_AVAILABLE_CACHE = False
        return False
    _IS_AVAILABLE_CACHE = True
    return True


def _reset_is_available_cache() -> None:
    """For tests — reset the cached availability probe. NOT for production."""
    global _IS_AVAILABLE_CACHE
    _IS_AVAILABLE_CACHE = None


def supports_model(model: str) -> bool:
    """True if ``model`` routes to the Gemini SDK.

    Matches:
      * ``gemini/<name>``    (Google AI Studio backend, GOOGLE_API_KEY auth).
      * ``vertex_ai/<name>`` (Vertex AI backend, ADC / Workload Identity auth).
    """
    if not model:
        return False
    if model.startswith(_GEMINI_PREFIX):
        return True
    if model.startswith(_VERTEX_PREFIX):
        return True
    return False


def _strip_prefix(model: str) -> str:
    """Return the bare Gemini model id for the SDK call.

    ``gemini/gemini-2.0-flash`` → ``gemini-2.0-flash``
    ``vertex_ai/gemini-2.0-flash`` → ``gemini-2.0-flash``
    """
    if model.startswith(_GEMINI_PREFIX):
        return model[len(_GEMINI_PREFIX):]
    if model.startswith(_VERTEX_PREFIX):
        return model[len(_VERTEX_PREFIX):]
    return model


def _build_client(
    model: str,
    api_key: str | None,
    base_url: str | None,
):
    """Construct the appropriate google-genai Client per backend.

    AI Studio backend (``gemini/*``):
      * Requires ``GOOGLE_API_KEY`` env var or explicit ``api_key`` kwarg.

    Vertex AI backend (``vertex_ai/*``):
      * Requires ``GOOGLE_CLOUD_PROJECT`` env var (no decorator-kwarg path
        in this PR — env-var-only, follow-up issue tracks credential kwargs).
      * ``GOOGLE_CLOUD_LOCATION`` optional; defaults to ``us-central1``.
      * Auth is via ADC (gcloud auth application-default login or Workload
        Identity in K8s). ``api_key`` is ignored on this backend; we WARN
        once if the caller passes one.

    The wrapper is built fresh per call (no caching) so K8s secret rotation
    works. The shared ``httpx.AsyncClient`` is forwarded through
    ``HttpOptions(httpx_async_client=...)`` for connection-pool reuse.
    """
    import google.genai as genai
    from google.genai.types import HttpOptions

    http_options = HttpOptions(httpx_async_client=_get_shared_httpx_client())

    if model.startswith(_VERTEX_PREFIX):
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            raise ValueError(
                "Native Vertex AI dispatch requires GOOGLE_CLOUD_PROJECT env "
                "var. Set GOOGLE_CLOUD_PROJECT (and optionally "
                "GOOGLE_CLOUD_LOCATION; default 'us-central1'), ensure ADC is "
                "configured (gcloud auth application-default login OR "
                "Workload Identity in K8s), or set MCP_MESH_NATIVE_LLM=0 to "
                "fall back to LiteLLM."
            )
        if api_key:
            # Vertex backend uses Google Cloud IAM, NOT api_key. Surface a
            # one-time WARN so users who mistakenly pass it know it's ignored.
            _warn_unsupported_kwarg_once("api_key (vertex_ai backend)")
        return genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=http_options,
        )

    # AI Studio backend.
    resolved_key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not resolved_key:
        raise ValueError(
            "Native Gemini (AI Studio) dispatch requires GOOGLE_API_KEY env "
            "var or explicit api_key argument. Set GOOGLE_API_KEY or pass "
            "api_key= to @mesh.llm_provider, or set MCP_MESH_NATIVE_LLM=0 to "
            "fall back to LiteLLM."
        )
    kwargs: dict[str, Any] = {"api_key": resolved_key, "http_options": http_options}
    return genai.Client(**kwargs)


# ---------------------------------------------------------------------------
# Translators (the meat of this PR)
# ---------------------------------------------------------------------------


def _extract_system_instruction(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split out system message(s) into a top-level systemInstruction string.

    Gemini's ``systemInstruction`` is a separate top-level request field,
    NOT an entry in the contents array. Walks ``messages``, pulls out any
    role=system entries, and returns ``(instruction, non_system_messages)``.

    Behavior:
      * No system messages → ``(None, messages)``.
      * Exactly one with string content → instruction is that string.
      * Multiple system messages → concatenated with double newlines.
      * List-content system messages → text parts joined with newlines (image
        parts in system messages are dropped — Gemini systemInstruction is
        text-only).
    """
    system_chunks: list[str] = []
    rest: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, str):
                if content:
                    system_chunks.append(content)
            elif isinstance(content, list):
                # Pull text from each text block; skip non-text (Gemini
                # systemInstruction is text-only).
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            system_chunks.append(text)
            elif content is not None:
                system_chunks.append(str(content))
        else:
            rest.append(msg)

    if not system_chunks:
        return None, rest
    return "\n\n".join(system_chunks), rest


def _build_tool_id_to_name_map(
    messages: list[dict[str, Any]],
) -> dict[str, str]:
    """Build a tool_call_id → tool_name map by walking assistant turns.

    Tool result messages (``role: tool``) carry ONLY ``tool_call_id``, not
    the function name — but Gemini's ``functionResponse`` part requires the
    NAME (it has no concept of tool-call ids). The id-to-name link comes
    from the immediately preceding assistant turn's ``tool_calls`` list.

    We walk all assistant messages once up front so the converter can do an
    O(1) lookup per tool result. Multiple turns are supported; the last
    binding for a given id wins (matches OpenAI/litellm conventions where
    ids are unique per request).
    """
    mapping: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            tc_id = tc.get("id")
            fn = tc.get("function") or {}
            tc_name = fn.get("name")
            if tc_id and tc_name:
                mapping[tc_id] = tc_name
    return mapping


def _translate_content_block_to_gemini(block: Any) -> dict | None:
    """Translate one OpenAI-shape content block to Gemini-native part shape.

    Returns a single part dict, or ``None`` to skip the block.

    Supported translations:
      * ``{"type": "text", "text": "..."}``
        → ``{"text": "..."}``
      * ``{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<data>"}}``
        → ``{"inline_data": {"mime_type": <mime>, "data": <data>}}``
      * ``{"type": "image_url", "image_url": {"url": "https://..."}}``
        → ``{"file_data": {"mime_type": "application/octet-stream",
                            "file_uri": <url>}}``

    Already-native parts (text/inline_data/file_data/function_call/
    function_response) pass through unchanged.

    Unknown block shapes pass through with a one-time WARN — surfaces the
    next OpenAI-shape block we forget to translate without flooding the log.
    """
    if not isinstance(block, dict):
        # Strings can appear inside a content list — treat as bare text.
        if isinstance(block, str):
            return {"text": block}
        return block

    btype = block.get("type")

    # Already-native part shapes — passthrough (idempotent).
    if "text" in block and btype is None:
        return block
    if "inline_data" in block or "inlineData" in block:
        return block
    if "file_data" in block or "fileData" in block:
        return block
    if "function_call" in block or "functionCall" in block:
        return block
    if "function_response" in block or "functionResponse" in block:
        return block

    if btype == "text":
        return {"text": block.get("text", "")}

    if btype == "image_url":
        image_url_field = block.get("image_url", {})
        # OpenAI typically uses ``image_url: {"url": "..."}``; some clients
        # pass a bare string. Accept both.
        if isinstance(image_url_field, str):
            url = image_url_field
        elif isinstance(image_url_field, dict):
            url = image_url_field.get("url", "")
        else:
            url = ""

        if not url:
            logger.warning(
                "image_url block missing url; passing through (will likely error)"
            )
            return block

        m = _DATA_URI_RE.match(url)
        if m:
            return {
                "inline_data": {
                    "mime_type": m.group("mime"),
                    "data": m.group("data"),
                }
            }

        if url.startswith(("http://", "https://")):
            # Gemini's fileData accepts arbitrary http(s) URIs but requires a
            # mime_type. We default to application/octet-stream when the
            # caller didn't supply one — Gemini will sniff in many cases.
            return {
                "file_data": {
                    "mime_type": "application/octet-stream",
                    "file_uri": url,
                }
            }

        logger.warning(
            "image_url block has unrecognized url scheme: %s; passing through",
            url[:50],
        )
        return block

    # Unknown block — passthrough + WARN once.
    _warn_unsupported_kwarg_once(f"content_block_type:{btype!r}")
    return block


def _translate_content_list_to_gemini(content: Any) -> list[dict]:
    """Apply ``_translate_content_block_to_gemini`` to a content list.

    If ``content`` is a string, wraps it in a single text part. If it's a
    list, returns a NEW list with each block translated (None entries are
    skipped). Anything else falls back to ``str()`` wrapped as text.
    """
    if isinstance(content, str):
        return [{"text": content}]
    if isinstance(content, list):
        out: list[dict] = []
        for block in content:
            translated = _translate_content_block_to_gemini(block)
            if translated is not None:
                out.append(translated)
        return out
    if content is None:
        return []
    return [{"text": str(content)}]


def _convert_messages_to_gemini(
    messages: list[dict[str, Any]],
    tool_id_to_name: dict[str, str],
) -> list[dict[str, Any]]:
    """Translate litellm-shape messages → Gemini contents array.

    Key transforms:
      * Roles: ``user`` stays ``user``; ``assistant`` becomes ``model``;
        ``tool`` becomes ``user`` with a single ``functionResponse`` part.
      * ``assistant`` with ``tool_calls`` → ``model`` role with one
        ``functionCall`` part per call (id is dropped — Gemini tool calls
        have no id; the preceding-turn id-to-name map is built upstream so
        tool results can find the right name).
      * ``tool`` result message → ``user`` role with a single
        ``functionResponse`` part. Name is looked up in ``tool_id_to_name``;
        if missing (mid-conversation reorder, tool result without preceding
        call, etc.) we WARN and emit a placeholder ``unknown_tool`` name —
        the request will likely fail at the API layer but the dispatch
        contract is preserved.

    Assumes ``messages`` does NOT contain system entries (caller already
    extracted them via ``_extract_system_instruction``).
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")

        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            tool_name = tool_id_to_name.get(tool_call_id)
            if not tool_name:
                logger.warning(
                    "Gemini tool result message missing name in id-map "
                    "(tool_call_id=%r); using placeholder 'unknown_tool'",
                    tool_call_id,
                )
                tool_name = "unknown_tool"

            content = msg.get("content", "")
            # Gemini's functionResponse.response is an arbitrary JSON object;
            # we conventionally wrap textual results under {"result": "..."}.
            # Already-dict results pass through to preserve structure.
            if isinstance(content, dict):
                response_value: Any = content
            elif isinstance(content, str):
                response_value = {"result": content}
            else:
                # Lists or other — try JSON serialization, fall back to repr.
                try:
                    response_value = {"result": json.dumps(content)}
                except (TypeError, ValueError):
                    response_value = {"result": repr(content)}

            out.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": tool_name,
                                "response": response_value,
                            }
                        }
                    ],
                }
            )
            continue

        if role == "assistant":
            parts: list[dict[str, Any]] = []
            text = msg.get("content")
            if isinstance(text, str) and text:
                parts.append({"text": text})
            elif isinstance(text, list):
                parts.extend(_translate_content_list_to_gemini(text))

            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args_raw = fn.get("arguments", "{}")
                try:
                    parsed_args = (
                        json.loads(args_raw)
                        if isinstance(args_raw, str)
                        else args_raw
                    )
                except (json.JSONDecodeError, ValueError):
                    parsed_args = {}
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
                parts.append(
                    {
                        "function_call": {
                            "name": fn.get("name", ""),
                            "args": parsed_args,
                        }
                    }
                )

            if not parts:
                # Skip empty assistant messages — Gemini rejects empty parts.
                continue
            out.append({"role": "model", "parts": parts})
            continue

        # user (default) or any other role — fall through as user.
        # Gemini only knows "user" and "model" roles in contents; map
        # anything unrecognized to "user" so the request stays valid.
        gemini_role = "user" if role != "model" else "model"
        parts = _translate_content_list_to_gemini(msg.get("content", ""))
        if not parts:
            # Still emit an empty-text placeholder so multi-turn ordering is
            # preserved (Gemini rejects truly empty parts arrays, but a
            # single empty-string text part is accepted).
            parts = [{"text": ""}]
        out.append({"role": gemini_role, "parts": parts})

    return out


# Whitelist of OpenAPI 3.0 Schema fields that Gemini's function_declarations
# parameters accept. Everything else is stripped by
# ``_sanitize_gemini_parameters_schema`` before it reaches the API — Gemini
# returns HTTP 400 INVALID_ARGUMENT for unknown fields like
# ``additionalProperties`` (which Pydantic-generated mesh tool schemas always
# emit) or ``$schema`` / ``title`` / ``$ref``.
#
# Reference: Gemini API "FunctionDeclaration" / "Schema" docs —
# https://ai.google.dev/api/caching#Schema
# (Gemini supports a documented subset of OpenAPI 3.0 Schema; the closed list
# of accepted fields is below. LiteLLM's Gemini adapter performs the
# equivalent translation internally; native dispatch must do the same.)
_GEMINI_SCHEMA_KEYS = frozenset({
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "properties",
    "required",
    "items",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
    "default",
    "example",
    "anyOf",
    "allOf",
    "oneOf",
    # NOTABLY ABSENT (rejected by Gemini): additionalProperties, $schema,
    # title, $ref, definitions, $defs, propertyNames, patternProperties,
    # exclusiveMinimum, exclusiveMaximum, multipleOf, const, not, contains.
})


def _sanitize_gemini_parameters_schema(schema: Any) -> Any:
    """Strip JSON-Schema fields Gemini's function_declarations doesn't accept.

    Gemini accepts an OpenAPI 3.0 Schema subset for function parameters.
    Fields like ``additionalProperties``, ``$schema``, ``title``, ``$ref``
    are rejected with HTTP 400 INVALID_ARGUMENT. Walk the schema recursively
    and keep only the whitelisted keys (see ``_GEMINI_SCHEMA_KEYS``).

    Mesh's tool schema generator (Pydantic-based) emits standard JSON Schema
    which always includes ``additionalProperties: False`` on object schemas;
    this helper bridges the gap so native dispatch matches LiteLLM's adapter
    behavior (LiteLLM has been silently doing this translation for us).

    Whitelist (not blacklist) approach is deliberate: the list of valid
    Gemini schema fields is fixed and documented; new JSON-Schema fields
    introduced by Pydantic upgrades would otherwise leak through and
    silently break tool calls again.

    ``properties`` needs special handling because it's a name → schema map
    (the keys are user-defined property names, NOT JSON-Schema field names),
    so we keep the keys as-is and only sanitize the value sub-schemas.
    """
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key not in _GEMINI_SCHEMA_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                # Property names are arbitrary identifiers — keep them
                # verbatim, sanitize each property's sub-schema.
                out[key] = {
                    prop_name: _sanitize_gemini_parameters_schema(prop_schema)
                    for prop_name, prop_schema in value.items()
                }
                continue
            if key == "required" and isinstance(value, list):
                # ``required`` is a list of property-name strings, not nested
                # schemas — pass through verbatim.
                out[key] = list(value)
                continue
            if key == "enum" and isinstance(value, list):
                # ``enum`` is a list of literal values, not nested schemas.
                out[key] = list(value)
                continue
            out[key] = _sanitize_gemini_parameters_schema(value)
        return out
    if isinstance(schema, list):
        return [_sanitize_gemini_parameters_schema(item) for item in schema]
    return schema


def _convert_tools(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Translate OpenAI/litellm tool schema → Gemini functionDeclarations.

    OpenAI shape (what mesh / litellm uses):
        [{"type": "function", "function": {"name": ..., "description": ...,
                                           "parameters": {...}}}, ...]

    Gemini shape:
        [{"function_declarations": [{"name": ..., "description": ...,
                                     "parameters": {...}}, ...]}]

    Note all declarations are bundled under ONE wrapper (Gemini expects a
    list of Tool objects each carrying a list of function_declarations; we
    use the canonical single-wrapper form because it's what the SDK
    documents and what litellm emits).

    The ``parameters`` field is sanitized via
    ``_sanitize_gemini_parameters_schema`` to strip JSON-Schema fields
    Gemini rejects (notably ``additionalProperties`` which mesh's
    Pydantic-based schema generator always emits).

    Tools already in Gemini shape (``function_declarations`` present)
    pass through unchanged.
    """
    if not tools:
        return None

    declarations: list[dict[str, Any]] = []
    passthrough_tools: list[dict[str, Any]] = []
    for tool in tools:
        if "function_declarations" in tool or "functionDeclarations" in tool:
            # Already-native — keep as a separate Tool entry.
            passthrough_tools.append(tool)
            continue
        fn = tool.get("function") or {}
        decl: dict[str, Any] = {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": _sanitize_gemini_parameters_schema(
                fn.get("parameters", {"type": "object", "properties": {}})
            ),
        }
        declarations.append(decl)

    out: list[dict[str, Any]] = []
    if declarations:
        out.append({"function_declarations": declarations})
    out.extend(passthrough_tools)
    return out or None


def _convert_tool_choice(tool_choice: Any) -> dict[str, Any] | None:
    """Translate OpenAI tool_choice → Gemini toolConfig.functionCallingConfig.

    | OpenAI                                          | Gemini                                                   |
    |-------------------------------------------------|----------------------------------------------------------|
    | ``"auto"``                                      | ``{function_calling_config: {mode: "AUTO"}}``            |
    | ``"none"``                                      | ``{function_calling_config: {mode: "NONE"}}``            |
    | ``"required"`` / ``"any"``                      | ``{function_calling_config: {mode: "ANY"}}``             |
    | ``{"type": "function", "function": {"name": "X"}}`` | ``{function_calling_config: {mode: "ANY", allowed_function_names: ["X"]}}`` |

    Returns ``None`` when ``tool_choice`` is None / unrecognized — the
    caller should omit ``tool_config`` entirely in that case (Gemini
    defaults to AUTO when tools are present).
    """
    if tool_choice is None:
        return None

    if tool_choice == "auto":
        return {"function_calling_config": {"mode": "AUTO"}}
    if tool_choice == "none":
        return {"function_calling_config": {"mode": "NONE"}}
    if tool_choice in ("required", "any"):
        return {"function_calling_config": {"mode": "ANY"}}

    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function") or {}
            name = fn.get("name")
            if name:
                return {
                    "function_calling_config": {
                        "mode": "ANY",
                        "allowed_function_names": [name],
                    }
                }
        # Best-effort passthrough if it already looks Gemini-shaped.
        if (
            "function_calling_config" in tool_choice
            or "functionCallingConfig" in tool_choice
        ):
            return tool_choice

    # Unknown — omit toolConfig (Gemini defaults to AUTO).
    return None


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

# Kwargs we know how to translate / forward; anything outside this set
# (and not in _GEMINI_HANDLED_KWARGS) triggers a once-per-key WARN so the
# next litellm-only knob we forget shows up early.
_GEMINI_PASSTHROUGH_KWARGS = frozenset({
    "messages",
    "tools",
    "tool_choice",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "top_k",
    "stop",
    "seed",
    "response_format",
    "response_mime_type",
    "presence_penalty",
    "frequency_penalty",
    "candidate_count",
})

# Keys explicitly handled (consumed or routed) inside this adapter — the
# WARN filter must not flag these as "dropped".
_GEMINI_HANDLED_KWARGS = frozenset({
    "model",
    "api_key",
    "base_url",
    "stream",
})


def _build_create_kwargs(
    request_params: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """Translate mesh/litellm-shape request_params → genai.Client kwargs.

    Returns a dict with keys ``model``, ``contents``, and ``config`` —
    matching ``aio.models.generate_content`` / ``generate_content_stream``.

    Translation steps:
      1. Extract the system message into a top-level ``system_instruction``.
      2. Build a ``tool_call_id → name`` map from the assistant turns so
         tool result messages can populate Gemini's ``functionResponse.name``.
      3. Convert messages → ``contents`` (role rename, multimodal block
         translation, tool_calls → functionCall parts, tool result →
         functionResponse part).
      4. Convert tools → ``functionDeclarations`` wrapper.
      5. Convert tool_choice → ``toolConfig.functionCallingConfig`` enum.
      6. Forward generation params (temperature, top_p, top_k, stop, seed)
         under their Gemini names (camel/snake — google-genai accepts both
         via dict input; we use snake_case for clarity).

    HINT-mode passthrough: ``response_format`` is forwarded as
    ``response_mime_type=application/json`` + ``response_schema``. The
    upstream ``GeminiHandler.prepare_request`` already strips
    ``response_format`` when tools are present (the HINT-mode workaround
    for the Gemini API infinite-loop bug); the adapter forwards whatever
    the handler hands it.
    """
    # 1. Extract system instruction.
    raw_messages = request_params.get("messages") or []
    system_instruction, non_system = _extract_system_instruction(raw_messages)

    # 2. Build tool_call_id → name map (for tool result conversion).
    tool_id_to_name = _build_tool_id_to_name_map(non_system)

    # 3. Convert messages → contents.
    contents = _convert_messages_to_gemini(non_system, tool_id_to_name)

    # 4. Convert tools.
    converted_tools = _convert_tools(request_params.get("tools"))

    # 5. Convert tool_choice → toolConfig.
    tool_config = _convert_tool_choice(request_params.get("tool_choice"))

    # 6. Assemble GenerateContentConfig dict.
    config: dict[str, Any] = {}
    if system_instruction:
        config["system_instruction"] = system_instruction
    if converted_tools:
        config["tools"] = converted_tools
    if tool_config:
        config["tool_config"] = tool_config

    # response_format → response_mime_type + response_schema (handler may
    # also be using HINT mode — in that case response_format is absent and
    # the JSON instructions live in the system prompt; this branch is a no-op).
    rf = request_params.get("response_format")
    if isinstance(rf, dict):
        if rf.get("type") == "json_schema":
            schema = (rf.get("json_schema") or {}).get("schema") or {}
            config["response_mime_type"] = "application/json"
            if schema:
                config["response_schema"] = schema
        elif rf.get("type") == "json_object":
            config["response_mime_type"] = "application/json"
    # Allow callers to set response_mime_type directly too.
    rmt = request_params.get("response_mime_type")
    if rmt is not None and "response_mime_type" not in config:
        config["response_mime_type"] = rmt

    # max_tokens / max_completion_tokens → max_output_tokens.
    # Explicit max_tokens=None must be DROPPED (don't forward as None which
    # Gemini would reject) — same lesson as openai_native.
    max_tokens = request_params.get("max_tokens")
    if max_tokens is None:
        max_tokens = request_params.get("max_completion_tokens")
    if max_tokens is not None:
        config["max_output_tokens"] = max_tokens

    # Generation params: forward under Gemini names. Drop None values so
    # callers passing ``temperature=None`` get the SDK default (Gemini
    # rejects None for these fields).
    for src, dst in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("top_k", "top_k"),
        ("stop", "stop_sequences"),
        ("seed", "seed"),
        ("presence_penalty", "presence_penalty"),
        ("frequency_penalty", "frequency_penalty"),
        ("candidate_count", "candidate_count"),
    ):
        value = request_params.get(src)
        if value is None:
            continue
        config[dst] = value

    # WARN-log any kwargs the adapter is silently dropping. Internal mesh
    # markers (``_mesh_*``) are not forwarded but should also not warn —
    # they're handled upstream in helpers._pop_mesh_*_flags. Dedupe per-key.
    for k in request_params:
        if k.startswith("_mesh_"):
            continue
        if k in _GEMINI_PASSTHROUGH_KWARGS:
            continue
        if k in _GEMINI_HANDLED_KWARGS:
            continue
        _warn_unsupported_kwarg_once(k)

    return {
        "model": _strip_prefix(model),
        "contents": contents,
        "config": config,
    }


# ---------------------------------------------------------------------------
# Response / chunk adaptation
# ---------------------------------------------------------------------------


# Gemini finish reasons → litellm-shape strings consumed by helpers.py.
_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "LANGUAGE": "stop",
    "OTHER": "stop",
    "FINISH_REASON_UNSPECIFIED": "stop",
}


def _normalize_finish_reason(raw: Any, has_tool_calls: bool) -> str:
    """Translate Gemini's FinishReason enum → litellm-style string.

    When the response contains tool/function calls and Gemini reports STOP,
    helpers.py's agentic loop expects ``tool_calls`` so it knows to invoke
    the tools. We surface that mapping here so the dispatch contract holds.
    """
    if raw is None:
        return "tool_calls" if has_tool_calls else "stop"
    # Enum members serialize to their str value by default.
    name = getattr(raw, "name", None) or str(raw)
    # Strip enum-like prefixes.
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    mapped = _FINISH_REASON_MAP.get(name, "stop")
    if has_tool_calls and mapped == "stop":
        return "tool_calls"
    return mapped


def _adapt_response(raw: Any, *, model: str) -> _Response:
    """Translate genai.GenerateContentResponse → litellm-shape ``_Response``.

    Walks ``candidates[0].content.parts`` collecting text parts (concatenated
    into ``message.content``) and function_call parts (each becomes a
    ``_ToolCall`` with synthesized id ``gemini_call_<index>``). usage_metadata
    maps to ``_Usage`` with prompt_token_count / candidates_token_count
    field-name translation.
    """
    candidates = getattr(raw, "candidates", None) or []
    first_candidate = candidates[0] if candidates else None

    text_parts: list[str] = []
    tool_calls: list[_ToolCall] = []
    raw_finish_reason: Any = None

    if first_candidate is not None:
        raw_finish_reason = getattr(first_candidate, "finish_reason", None)
        content = getattr(first_candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        for part in parts or []:
            text = getattr(part, "text", None)
            if text:
                text_parts.append(text)
            fc = getattr(part, "function_call", None)
            if fc is not None:
                fc_name = getattr(fc, "name", "") or ""
                fc_args = getattr(fc, "args", {}) or {}
                # Gemini args come back as a dict; the litellm contract
                # carries arguments as a JSON string for downstream parsers.
                try:
                    args_str = json.dumps(fc_args)
                except (TypeError, ValueError):
                    args_str = "{}"
                # Synthesize a stable id since Gemini has no tool-call ids.
                synth_id = f"gemini_call_{len(tool_calls)}"
                tool_calls.append(
                    _ToolCall(id=synth_id, name=fc_name, arguments=args_str)
                )

    finish_reason = _normalize_finish_reason(
        raw_finish_reason, has_tool_calls=bool(tool_calls)
    )

    message = _Message(
        content="".join(text_parts) if text_parts else None,
        role="assistant",
        tool_calls=tool_calls or None,
    )

    usage_obj = getattr(raw, "usage_metadata", None)
    if usage_obj is not None:
        usage = _Usage(
            prompt_tokens=getattr(usage_obj, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage_obj, "candidates_token_count", 0) or 0,
        )
    else:
        usage = None

    # Gemini surfaces the resolved model id as ``model_version`` on the
    # response (``response.model`` does not exist). Fall back to the request
    # model if absent.
    response_model = getattr(raw, "model_version", None) or model

    return _Response(
        message=message,
        usage=usage,
        model=response_model,
        finish_reason=finish_reason,
    )


def _adapt_stream_chunk(
    raw_chunk: Any,
    *,
    model: str,
    tool_call_index_state: list[int],
) -> _StreamChunk:
    """Translate one streamed GenerateContentResponse chunk → ``_StreamChunk``.

    Each Gemini chunk carries:
      * Optional ``candidates[0].content.parts`` with text deltas and/or
        complete ``function_call`` parts (Gemini does NOT stream function
        call argument fragments — function_call appears as a single complete
        part within one chunk).
      * Optional ``usage_metadata`` (cumulative; emitted on most chunks
        including the final one).

    ``tool_call_index_state`` is a single-element list used as a mutable
    integer counter so the synthesized id stays monotonic across chunks
    yielded by the same stream — Python closures can't rebind ints.
    """
    candidates = getattr(raw_chunk, "candidates", None) or []
    first_candidate = candidates[0] if candidates else None

    content_str: str | None = None
    tool_call_deltas: list[_StreamToolCallDelta] | None = None
    raw_finish_reason: Any = None

    if first_candidate is not None:
        raw_finish_reason = getattr(first_candidate, "finish_reason", None)
        content = getattr(first_candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        text_buf: list[str] = []
        for part in parts or []:
            text = getattr(part, "text", None)
            if text:
                text_buf.append(text)
            fc = getattr(part, "function_call", None)
            if fc is not None:
                if tool_call_deltas is None:
                    tool_call_deltas = []
                fc_name = getattr(fc, "name", "") or ""
                fc_args = getattr(fc, "args", {}) or {}
                try:
                    args_str = json.dumps(fc_args)
                except (TypeError, ValueError):
                    args_str = "{}"
                idx = tool_call_index_state[0]
                tool_call_index_state[0] = idx + 1
                tool_call_deltas.append(
                    _StreamToolCallDelta(
                        index=idx,
                        id=f"gemini_call_{idx}",
                        name=fc_name,
                        arguments=args_str,
                    )
                )
        if text_buf:
            content_str = "".join(text_buf)

    finish_reason: str | None = None
    if raw_finish_reason is not None:
        finish_reason = _normalize_finish_reason(
            raw_finish_reason,
            has_tool_calls=bool(tool_call_deltas),
        )

    usage_obj = getattr(raw_chunk, "usage_metadata", None)
    usage: _Usage | None = None
    if usage_obj is not None:
        usage = _Usage(
            prompt_tokens=getattr(usage_obj, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage_obj, "candidates_token_count", 0) or 0,
        )

    chunk_model = getattr(raw_chunk, "model_version", None) or model

    return _StreamChunk(
        delta=_Delta(content=content_str, tool_calls=tool_call_deltas),
        usage=usage,
        model=chunk_model,
        finish_reason=finish_reason,
    )


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------


async def complete(
    request_params: dict[str, Any],
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> _Response:
    """Run a buffered Gemini completion and adapt to litellm-shape response.

    The upstream ``GeminiHandler.prepare_request`` makes the
    response_format-vs-HINT decision (Gemini API has an infinite-tool-loop
    bug for ``response_format + tools`` — handler omits response_format in
    that case and routes the schema through HINT mode in the system prompt
    instead). The adapter just forwards whatever request_params carries.
    """
    client = _build_client(model, api_key, base_url)
    create_kwargs = _build_create_kwargs(request_params, model=model)

    raw = await client.aio.models.generate_content(**create_kwargs)
    return _adapt_response(raw, model=create_kwargs["model"])


async def complete_stream(
    request_params: dict[str, Any],
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[Any]:
    """Stream a Gemini completion as litellm-shape chunks.

    google-genai exposes streaming via ``await
    client.aio.models.generate_content_stream(...)`` which returns an
    async iterator of ``GenerateContentResponse`` chunks (each carrying
    incremental text + cumulative usage_metadata; function_calls appear as
    complete parts within a single chunk, not streamed-as-fragments).

    Best-effort usage emission: if the stream is interrupted before a
    final usage chunk arrives (server cutoff, consumer aclose, network
    drop), the ``finally`` block emits a fallback usage chunk built from
    the last counters we observed so telemetry doesn't silently record
    0 tokens for partial generations.
    """
    client = _build_client(model, api_key, base_url)
    create_kwargs = _build_create_kwargs(request_params, model=model)

    # Single-element list as a mutable int counter so the synthesized
    # tool-call id stays monotonic across chunks (Python closures can't
    # rebind ints; a list cell can).
    tool_call_index_state: list[int] = [0]

    # Track usage for finally-block fallback (telemetry integrity if stream
    # is interrupted — same pattern as anthropic_native / openai_native).
    last_input_tokens = 0
    last_output_tokens = 0
    last_model: str = create_kwargs["model"]
    # Tracks whether an authoritative usage chunk was successfully delivered
    # to the consumer. Set True ONLY after the yield returns — so any
    # failure mode (stream raises, consumer cancels mid-yield) leaves it
    # False and the ``finally`` block emits the best-effort fallback.
    final_usage_emitted = False

    try:
        stream = await client.aio.models.generate_content_stream(**create_kwargs)
        async for raw_chunk in stream:
            chunk = _adapt_stream_chunk(
                raw_chunk,
                model=create_kwargs["model"],
                tool_call_index_state=tool_call_index_state,
            )
            if chunk.model:
                last_model = chunk.model
            if chunk.usage is not None:
                last_input_tokens = chunk.usage.prompt_tokens
                last_output_tokens = chunk.usage.completion_tokens
                yield chunk
                # Set the flag AFTER the yield so a consumer abort
                # mid-yield falls into the finally fallback path.
                final_usage_emitted = True
                continue
            yield chunk
    finally:
        # If no authoritative usage chunk reached the consumer (server
        # cutoff, consumer cancelled mid-yield, network drop, etc.), emit
        # a best-effort usage chunk built from the last counters we
        # observed. Otherwise telemetry would silently record zero tokens
        # for any interrupted stream — masking real cost on partial
        # generations.
        if not final_usage_emitted and (last_input_tokens or last_output_tokens):
            try:
                yield _StreamChunk(
                    delta=_Delta(),
                    usage=_Usage(
                        prompt_tokens=last_input_tokens,
                        completion_tokens=last_output_tokens,
                    ),
                    model=last_model,
                )
            except (GeneratorExit, StopAsyncIteration):
                # The consumer has already called ``aclose()`` on this async
                # generator, so executing ``yield`` inside ``finally`` raises
                # GeneratorExit (or in rare cases StopAsyncIteration). Python
                # forbids re-raising during finally cleanup — and there's
                # nowhere to deliver the fallback usage chunk anyway. Swallow
                # silently and let normal generator teardown proceed.
                pass


# ---------------------------------------------------------------------------
# Fallback-logging helpers
# ---------------------------------------------------------------------------

_logged_fallback_once = False


def log_fallback_once() -> None:
    """Emit the LiteLLM-fallback notice exactly once per process.

    Called from ``GeminiHandler.has_native()`` when native dispatch was
    attempted (the default) but the ``google.genai`` SDK is not importable.
    In normal installs the SDK is a base dep so this branch should never
    fire — kept for symmetry with the Anthropic / OpenAI paths and to guard
    against custom installs that strip the SDK.
    """
    global _logged_fallback_once
    if _logged_fallback_once:
        return
    _logged_fallback_once = True
    logger.info(
        "Install `mcp-mesh[gemini]` for native SDK with full feature "
        "support — falling back to LiteLLM"
    )


def is_fallback_logged() -> bool:
    """True once :func:`log_fallback_once` has emitted its notice.

    Lets callers (notably ``GeminiHandler.has_native``) skip the call
    entirely on the hot path after the first miss — avoids one
    function-frame per request once we've already published the install
    nudge.
    """
    return _logged_fallback_once


# Module-level dedupe set for the unsupported-kwarg WARN. WARN once per
# unique kwarg name across the lifetime of the process — high-volume
# providers receiving the same litellm-only kwarg every request would
# otherwise flood the log with identical messages (unbounded growth
# pre-fix).
_logged_unsupported_kwargs: set[str] = set()


def _warn_unsupported_kwarg_once(key: str) -> None:
    """WARN once per unique unsupported kwarg name.

    Used by ``_build_create_kwargs`` to surface litellm-only knobs the
    adapter is silently dropping (or new fields the google-genai SDK
    doesn't accept yet) without logging on every single request.
    """
    if key in _logged_unsupported_kwargs:
        return
    _logged_unsupported_kwargs.add(key)
    logger.warning(
        "Native Gemini adapter dropping unsupported kwarg: '%s' "
        "(LiteLLM-only — not forwarded to google.genai.Client.aio.models.generate_content)",
        key,
    )

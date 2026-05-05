"""Unit tests for the native Gemini SDK adapter (issue #834 PR 3).

Covers:
  * is_available() reflects ImportError of the SDK and caches the probe
  * supports_model() matches the gemini/* and vertex_ai/* prefixes
  * _strip_prefix() correctness for both prefixes
  * _build_client() backend dispatch + credential validation
  * Translator surface (the bulk of this PR's complexity):
    - System message extraction → top-level systemInstruction
    - Role rename: assistant → model
    - Tool result conversion via tool_call_id → name map
    - OpenAI tools → functionDeclarations wrapper
    - tool_choice → toolConfig.functionCallingConfig enum
    - Multimodal block translation (data-URI → inlineData; URL → fileData)
  * _build_create_kwargs() request shaping + per-key WARN dedupe
  * _adapt_response() text + function_calls + usage_metadata mapping
  * complete_stream() chunk shape + best-effort usage emission
  * Shared httpx pool reused across calls; lazy-per-call client construction

Real network calls are mocked.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "google.genai", reason="native Gemini adapter requires the google-genai SDK"
)

from _mcp_mesh.engine.native_clients import gemini_native


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestIsAvailable:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """is_available() caches its result module-wide; reset between tests
        in this class so each one re-probes the import."""
        gemini_native._reset_is_available_cache()
        yield
        gemini_native._reset_is_available_cache()

    def test_returns_true_when_sdk_importable(self):
        # The SDK is installed in the test environment; this should be True.
        assert gemini_native.is_available() is True

    def test_returns_false_when_import_fails(self, monkeypatch):
        """Simulate the SDK being absent by stubbing __import__ to raise."""
        original_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "google.genai" or name.startswith("google.genai."):
                raise ImportError("No module named 'google.genai'")
            return original_import(name, *args, **kwargs)

        # Drop the cached module so the function re-evaluates the import.
        monkeypatch.delitem(sys.modules, "google.genai", raising=False)
        with patch("builtins.__import__", side_effect=_fake_import):
            assert gemini_native.is_available() is False

    def test_caches_result_across_calls(self):
        """Once probed, is_available() must not re-import on every call —
        the SDK presence does not change at runtime and the per-call import
        was showing up as needless overhead on the dispatch-decision path.
        """
        original_import = builtins.__import__
        call_count = {"n": 0}

        def _counting_import(name, *args, **kwargs):
            if name == "google.genai":
                call_count["n"] += 1
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_counting_import):
            gemini_native.is_available()
            gemini_native.is_available()
            gemini_native.is_available()

        # Exactly one import attempt across three calls.
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# supports_model() and _strip_prefix()
# ---------------------------------------------------------------------------


class TestSupportsModel:
    @pytest.mark.parametrize(
        "model",
        [
            "gemini/gemini-2.0-flash",
            "gemini/gemini-1.5-pro",
            "gemini/gemini-3-pro-preview",
            "vertex_ai/gemini-2.0-flash",
            "vertex_ai/gemini-1.5-pro",
        ],
    )
    def test_supported_prefixes(self, model):
        assert gemini_native.supports_model(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "openai/gpt-4o",
            "bedrock/anthropic.claude-3-5-sonnet",
            "azure/gpt-4o",
            "gemini-2.0-flash",  # bare, no prefix
            "",
        ],
    )
    def test_unsupported(self, model):
        assert gemini_native.supports_model(model) is False

    def test_none_returns_false(self):
        # Defensive: None should not crash; treat as unsupported.
        assert gemini_native.supports_model(None or "") is False


class TestStripPrefix:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("gemini/gemini-2.0-flash", "gemini-2.0-flash"),
            ("gemini/gemini-1.5-pro", "gemini-1.5-pro"),
            ("vertex_ai/gemini-2.0-flash", "gemini-2.0-flash"),
            ("vertex_ai/gemini-3-pro-preview", "gemini-3-pro-preview"),
            ("gemini-2.0-flash", "gemini-2.0-flash"),  # bare passthrough
        ],
    )
    def test_strip_prefix(self, model, expected):
        assert gemini_native._strip_prefix(model) == expected


# ---------------------------------------------------------------------------
# Backend selection / _build_client
# ---------------------------------------------------------------------------


class TestBuildClient:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        """Make sure GOOGLE_* env vars don't leak between tests."""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        yield

    def test_ai_studio_with_explicit_api_key(self, monkeypatch):
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        gemini_native._build_client("gemini/gemini-2.0-flash", "GAK-test", None)
        kwargs = cls_mock.call_args.kwargs
        assert kwargs["api_key"] == "GAK-test"
        # AI Studio backend must NOT pass vertexai/project/location.
        assert "vertexai" not in kwargs
        assert "project" not in kwargs

    def test_ai_studio_with_env_var(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-from-env")
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        gemini_native._build_client("gemini/gemini-2.0-flash", None, None)
        # api_key flows from env into the resolved kwarg.
        kwargs = cls_mock.call_args.kwargs
        assert kwargs["api_key"] == "GAK-from-env"

    def test_ai_studio_raises_when_no_api_key(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            gemini_native._build_client("gemini/gemini-2.0-flash", None, None)
        msg = str(exc_info.value)
        assert "GOOGLE_API_KEY" in msg
        assert "MCP_MESH_NATIVE_LLM=0" in msg

    def test_vertex_with_project_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-gcp-project")
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        gemini_native._build_client("vertex_ai/gemini-2.0-flash", None, None)
        kwargs = cls_mock.call_args.kwargs
        assert kwargs["vertexai"] is True
        assert kwargs["project"] == "my-gcp-project"
        # Default location applied when GOOGLE_CLOUD_LOCATION is unset.
        assert kwargs["location"] == "us-central1"

    def test_vertex_with_explicit_location(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-gcp-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        gemini_native._build_client("vertex_ai/gemini-2.0-flash", None, None)
        kwargs = cls_mock.call_args.kwargs
        assert kwargs["location"] == "europe-west4"

    def test_vertex_raises_when_no_project(self, monkeypatch):
        # Stub ADC auto-derive to return None — simulates a deployment
        # where neither GOOGLE_CLOUD_PROJECT env var nor ADC carries a
        # project. Without this stub the test would pick up the test
        # author's gcloud-default-login project.
        monkeypatch.setattr(
            gemini_native, "_derive_vertex_project_from_adc", lambda: None
        )
        with pytest.raises(ValueError) as exc_info:
            gemini_native._build_client("vertex_ai/gemini-2.0-flash", None, None)
        msg = str(exc_info.value)
        assert "GOOGLE_CLOUD_PROJECT" in msg
        assert "MCP_MESH_NATIVE_LLM=0" in msg

    def test_vertex_auto_derives_project_from_adc(self, monkeypatch):
        """When GOOGLE_CLOUD_PROJECT is unset, fall back to ADC-derived
        project — matches LiteLLM's behavior and works seamlessly with
        Workload Identity / gcloud-default-login (no env var required)."""
        monkeypatch.setattr(
            gemini_native,
            "_derive_vertex_project_from_adc",
            lambda: "adc-derived-project",
        )
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        gemini_native._build_client("vertex_ai/gemini-2.0-flash", None, None)
        kwargs = cls_mock.call_args.kwargs
        assert kwargs["project"] == "adc-derived-project"
        assert kwargs["vertexai"] is True

    def test_vertex_env_var_wins_over_adc_derive(self, monkeypatch):
        """Explicit GOOGLE_CLOUD_PROJECT env var takes precedence over the
        ADC-derived project — auto-derive is a fallback, not an override."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "explicit-env-project")
        # Make the ADC stub fail loudly if it's called — env var should
        # short-circuit the derive path.
        monkeypatch.setattr(
            gemini_native,
            "_derive_vertex_project_from_adc",
            lambda: pytest.fail(
                "ADC derive must not be called when env var is set"
            ),
        )
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        gemini_native._build_client("vertex_ai/gemini-2.0-flash", None, None)
        assert cls_mock.call_args.kwargs["project"] == "explicit-env-project"

    def test_derive_vertex_project_calls_google_auth_default(
        self, monkeypatch
    ):
        """The derive helper calls google.auth.default() and returns the
        second tuple element (the resolved default project)."""
        import google.auth as _ga

        monkeypatch.setattr(
            _ga, "default", lambda: (MagicMock(), "auth-default-project")
        )
        assert (
            gemini_native._derive_vertex_project_from_adc()
            == "auth-default-project"
        )

    def test_derive_vertex_project_returns_none_when_auth_unavailable(
        self, monkeypatch
    ):
        """If google.auth isn't importable (custom install stripping the
        transitive dep), the helper returns None — caller surfaces the
        explicit-env-var error message."""
        original_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "google.auth" or name.startswith("google.auth."):
                raise ImportError("No module named 'google.auth'")
            return original_import(name, *args, **kwargs)

        monkeypatch.delitem(sys.modules, "google.auth", raising=False)
        with patch("builtins.__import__", side_effect=_fake_import):
            assert gemini_native._derive_vertex_project_from_adc() is None

    def test_derive_vertex_project_returns_none_when_default_raises(
        self, monkeypatch
    ):
        """ADC has many failure modes (no creds, no metadata server, etc.).
        The helper swallows them and returns None so the caller surfaces
        the explicit-env-var error message."""
        import google.auth as _ga

        def _raise(*_args, **_kwargs):
            raise RuntimeError("Could not automatically determine credentials")

        monkeypatch.setattr(_ga, "default", _raise)
        assert gemini_native._derive_vertex_project_from_adc() is None

    def test_vertex_ignores_api_key_with_warn(self, monkeypatch, caplog):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-gcp-project")
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        # Reset WARN dedupe so this test is order-independent.
        gemini_native._logged_unsupported_kwargs.clear()
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            gemini_native._build_client(
                "vertex_ai/gemini-2.0-flash", "GAK-ignored", None
            )
        # api_key MUST NOT be forwarded on the Vertex backend.
        kwargs = cls_mock.call_args.kwargs
        assert "api_key" not in kwargs
        # And a one-time WARN should fire so users see the misuse.
        assert any(
            "vertex_ai backend" in r.getMessage() for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Translators: system message extraction
# ---------------------------------------------------------------------------


class TestExtractSystemInstruction:
    def test_no_system_message(self):
        msgs = [{"role": "user", "content": "Hi"}]
        instruction, rest = gemini_native._extract_system_instruction(msgs)
        assert instruction is None
        assert rest == msgs

    def test_single_system_message_string_content(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        instruction, rest = gemini_native._extract_system_instruction(msgs)
        assert instruction == "You are helpful."
        assert rest == [{"role": "user", "content": "Hi"}]

    def test_multiple_system_messages_concatenated(self):
        msgs = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "system", "content": "Be concise."},
        ]
        instruction, rest = gemini_native._extract_system_instruction(msgs)
        assert instruction == "Be helpful.\n\nBe concise."
        assert rest == [{"role": "user", "content": "Hi"}]

    def test_system_message_with_list_content(self):
        msgs = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "Be helpful."},
                    {"type": "text", "text": "Always cite sources."},
                ],
            },
            {"role": "user", "content": "Hi"},
        ]
        instruction, _ = gemini_native._extract_system_instruction(msgs)
        # Both text blocks joined.
        assert "Be helpful." in instruction
        assert "Always cite sources." in instruction


# ---------------------------------------------------------------------------
# Translators: messages → contents
# ---------------------------------------------------------------------------


class TestConvertMessages:
    def test_user_role_stays_user(self):
        out = gemini_native._convert_messages_to_gemini(
            [{"role": "user", "content": "Hello"}], {}
        )
        assert out == [{"role": "user", "parts": [{"text": "Hello"}]}]

    def test_assistant_role_renamed_to_model(self):
        out = gemini_native._convert_messages_to_gemini(
            [{"role": "assistant", "content": "Hi there"}], {}
        )
        assert out == [{"role": "model", "parts": [{"text": "Hi there"}]}]

    def test_assistant_with_tool_calls_emits_function_call_parts(self):
        out = gemini_native._convert_messages_to_gemini(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "NYC"}',
                            },
                        }
                    ],
                }
            ],
            {},
        )
        assert len(out) == 1
        assert out[0]["role"] == "model"
        # function_call part: NAME present, NO id (Gemini has no tool-call ids).
        fc_parts = [p for p in out[0]["parts"] if "function_call" in p]
        assert len(fc_parts) == 1
        fc = fc_parts[0]["function_call"]
        assert fc["name"] == "get_weather"
        assert fc["args"] == {"city": "NYC"}
        # No id field anywhere on the part.
        assert "id" not in fc

    def test_tool_result_converted_to_user_with_function_response(self):
        # tool_call_id → name map provided.
        id_map = {"call_1": "get_weather"}
        out = gemini_native._convert_messages_to_gemini(
            [
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "Sunny, 72°F",
                }
            ],
            id_map,
        )
        assert len(out) == 1
        assert out[0]["role"] == "user"
        fr_parts = [p for p in out[0]["parts"] if "function_response" in p]
        assert len(fr_parts) == 1
        fr = fr_parts[0]["function_response"]
        assert fr["name"] == "get_weather"
        # String content wrapped under {"result": ...}.
        assert fr["response"] == {"result": "Sunny, 72°F"}

    def test_tool_result_id_to_name_lookup_via_helper(self):
        """The id-map builder walks assistant turns; verify end-to-end that
        a tool result message in a multi-turn conversation finds its name."""
        msgs = [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_xyz",
                        "function": {"name": "get_weather", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_xyz", "content": "rain"},
        ]
        id_map = gemini_native._build_tool_id_to_name_map(msgs)
        assert id_map == {"call_xyz": "get_weather"}

        out = gemini_native._convert_messages_to_gemini(msgs, id_map)
        # Tool result is the last message → user role + functionResponse.
        last = out[-1]
        assert last["role"] == "user"
        fr = last["parts"][0]["function_response"]
        assert fr["name"] == "get_weather"

    def test_missing_name_in_id_map_warns_and_uses_placeholder(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            out = gemini_native._convert_messages_to_gemini(
                [
                    {
                        "role": "tool",
                        "tool_call_id": "missing_id",
                        "content": "result",
                    }
                ],
                {},  # empty id-map
            )
        fr = out[0]["parts"][0]["function_response"]
        assert fr["name"] == "unknown_tool"
        # WARN must mention the missing id.
        assert any("missing_id" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Translators: tools / tool_choice
# ---------------------------------------------------------------------------


class TestConvertTools:
    def test_openai_tools_to_function_declarations(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Look up the weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Send mail",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]
        out = gemini_native._convert_tools(tools)
        # ALL declarations bundled under ONE wrapper.
        assert len(out) == 1
        assert "function_declarations" in out[0]
        decls = out[0]["function_declarations"]
        assert len(decls) == 2
        names = sorted(d["name"] for d in decls)
        assert names == ["get_weather", "send_email"]

    def test_empty_tools_returns_none(self):
        assert gemini_native._convert_tools(None) is None
        assert gemini_native._convert_tools([]) is None

    def test_already_native_passthrough(self):
        tools = [
            {
                "function_declarations": [
                    {"name": "foo", "description": "", "parameters": {}}
                ]
            }
        ]
        out = gemini_native._convert_tools(tools)
        assert out == tools

    def test_convert_tools_applies_sanitization(self):
        """Mesh's Pydantic-generated schemas always emit
        ``additionalProperties: False`` — Gemini rejects that field with
        HTTP 400. Verify _convert_tools strips it (and other unsupported
        JSON-Schema fields) so native dispatch matches LiteLLM behavior.
        """
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Look up the weather",
                    "parameters": {
                        "type": "object",
                        "title": "WeatherParams",  # rejected by Gemini
                        "additionalProperties": False,  # rejected by Gemini
                        "$schema": "http://json-schema.org/draft-07/schema#",  # rejected
                        "properties": {
                            "city": {
                                "type": "string",
                                "title": "City",  # nested — also stripped
                            },
                        },
                        "required": ["city"],
                    },
                },
            },
        ]
        out = gemini_native._convert_tools(tools)
        decl = out[0]["function_declarations"][0]
        params = decl["parameters"]
        # Stripped:
        assert "additionalProperties" not in params
        assert "title" not in params
        assert "$schema" not in params
        assert "title" not in params["properties"]["city"]
        # Preserved:
        assert params["type"] == "object"
        assert params["properties"]["city"]["type"] == "string"
        assert params["required"] == ["city"]

    def test_convert_tools_preserves_function_metadata(self):
        """Sanitization must only touch ``parameters`` — ``name`` and
        ``description`` round-trip untouched through the translation."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Send an email to a recipient",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"to": {"type": "string"}},
                    },
                },
            },
        ]
        out = gemini_native._convert_tools(tools)
        decl = out[0]["function_declarations"][0]
        assert decl["name"] == "send_email"
        assert decl["description"] == "Send an email to a recipient"


class TestSanitizeGeminiParametersSchema:
    """Direct unit tests for the schema-sanitization helper.

    Gemini's function_declarations.parameters accept an OpenAPI 3.0 Schema
    subset. Anything outside ``_GEMINI_SCHEMA_KEYS`` is rejected with
    HTTP 400 INVALID_ARGUMENT (per
    https://ai.google.dev/api/caching#Schema). This helper bridges the
    gap so mesh's Pydantic-generated schemas (which always include
    ``additionalProperties: False``) work with native dispatch.
    """

    def test_strips_additional_properties(self):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"city": {"type": "string"}},
        }
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        assert "additionalProperties" not in out
        assert out == {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        }

    def test_strips_dollar_schema(self):
        schema = {
            "type": "object",
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {},
        }
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        assert "$schema" not in out

    def test_strips_title(self):
        schema = {"type": "object", "title": "MyParams", "properties": {}}
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        assert "title" not in out

    def test_strips_dollar_ref_and_definitions(self):
        """Pydantic emits ``$ref`` + ``definitions`` for nested models;
        both are rejected by Gemini and must be stripped."""
        schema = {
            "type": "object",
            "$ref": "#/definitions/Foo",
            "definitions": {"Foo": {"type": "string"}},
            "properties": {},
        }
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        assert "$ref" not in out
        assert "definitions" not in out

    def test_keeps_required_fields(self):
        schema = {
            "type": "object",
            "description": "A test schema",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name",
                    "enum": ["NYC", "LA"],
                },
            },
            "required": ["city"],
        }
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        assert out == schema

    def test_recursive_strips_nested_objects(self):
        """Nested object schemas (properties.foo.additionalProperties) are
        also sanitized — the helper walks recursively."""
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "address": {
                    "type": "object",
                    "additionalProperties": False,
                    "title": "Address",
                    "properties": {
                        "street": {"type": "string", "title": "Street"},
                    },
                },
            },
        }
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        assert "additionalProperties" not in out
        assert "additionalProperties" not in out["properties"]["address"]
        assert "title" not in out["properties"]["address"]
        assert "title" not in out["properties"]["address"]["properties"]["street"]
        # Structural fields preserved:
        assert out["properties"]["address"]["type"] == "object"
        assert (
            out["properties"]["address"]["properties"]["street"]["type"]
            == "string"
        )

    def test_recursive_strips_array_items(self):
        """Array ``items`` schemas are recursively sanitized too."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "title": "Item",
                "properties": {"id": {"type": "integer"}},
            },
        }
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        assert "additionalProperties" not in out["items"]
        assert "title" not in out["items"]
        assert out["items"]["type"] == "object"
        assert out["items"]["properties"]["id"]["type"] == "integer"

    def test_handles_anyof_oneof_allof(self):
        """Union types are preserved; each subschema is sanitized."""
        schema = {
            "anyOf": [
                {"type": "string", "title": "AsString"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"x": {"type": "integer"}},
                },
            ],
            "oneOf": [{"type": "null", "title": "Nothing"}],
            "allOf": [{"type": "object", "$schema": "x", "properties": {}}],
        }
        out = gemini_native._sanitize_gemini_parameters_schema(schema)
        # anyOf preserved as a list, sanitization applied to each entry.
        assert "anyOf" in out and isinstance(out["anyOf"], list)
        assert len(out["anyOf"]) == 2
        assert "title" not in out["anyOf"][0]
        assert "additionalProperties" not in out["anyOf"][1]
        # oneOf / allOf likewise.
        assert "title" not in out["oneOf"][0]
        assert "$schema" not in out["allOf"][0]

    def test_passes_through_non_dict_non_list(self):
        """Primitive leaves (str, int, bool, None) round-trip unchanged."""
        assert gemini_native._sanitize_gemini_parameters_schema("foo") == "foo"
        assert gemini_native._sanitize_gemini_parameters_schema(42) == 42
        assert gemini_native._sanitize_gemini_parameters_schema(True) is True
        assert gemini_native._sanitize_gemini_parameters_schema(None) is None

    def test_empty_dict_returns_empty_dict(self):
        assert gemini_native._sanitize_gemini_parameters_schema({}) == {}


class TestConvertToolChoice:
    def test_auto(self):
        assert gemini_native._convert_tool_choice("auto") == {
            "function_calling_config": {"mode": "AUTO"}
        }

    def test_none(self):
        assert gemini_native._convert_tool_choice("none") == {
            "function_calling_config": {"mode": "NONE"}
        }

    @pytest.mark.parametrize("value", ["required", "any"])
    def test_required_and_any(self, value):
        assert gemini_native._convert_tool_choice(value) == {
            "function_calling_config": {"mode": "ANY"}
        }

    def test_function_dict_with_name(self):
        choice = {"type": "function", "function": {"name": "foo"}}
        assert gemini_native._convert_tool_choice(choice) == {
            "function_calling_config": {
                "mode": "ANY",
                "allowed_function_names": ["foo"],
            }
        }

    def test_none_input_returns_none(self):
        assert gemini_native._convert_tool_choice(None) is None

    def test_unrecognized_returns_none(self):
        assert gemini_native._convert_tool_choice("not_a_real_value") is None


# ---------------------------------------------------------------------------
# Translators: multimodal content blocks
# ---------------------------------------------------------------------------


class TestTranslateContentBlock:
    def test_text_block(self):
        out = gemini_native._translate_content_block_to_gemini(
            {"type": "text", "text": "hello"}
        )
        assert out == {"text": "hello"}

    def test_data_uri_image_block(self):
        out = gemini_native._translate_content_block_to_gemini(
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,abc123",
                },
            }
        )
        assert out == {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": "abc123",
            }
        }

    def test_https_url_image_block(self):
        out = gemini_native._translate_content_block_to_gemini(
            {
                "type": "image_url",
                "image_url": {"url": "https://example.com/cat.png"},
            }
        )
        assert out == {
            "file_data": {
                "mime_type": "application/octet-stream",
                "file_uri": "https://example.com/cat.png",
            }
        }

    def test_already_native_text_passthrough(self):
        block = {"text": "already native"}
        out = gemini_native._translate_content_block_to_gemini(block)
        assert out == block

    def test_already_native_inline_data_passthrough(self):
        block = {"inline_data": {"mime_type": "image/png", "data": "xyz"}}
        out = gemini_native._translate_content_block_to_gemini(block)
        assert out == block

    def test_string_block_treated_as_text(self):
        # A bare string inside a content list — common for some clients.
        out = gemini_native._translate_content_block_to_gemini("hello")
        assert out == {"text": "hello"}


# ---------------------------------------------------------------------------
# _build_create_kwargs() — request shaping
# ---------------------------------------------------------------------------


class TestBuildCreateKwargs:
    def test_full_happy_path(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Hi"},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "noop",
                            "description": "",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "tool_choice": "auto",
                "temperature": 0.3,
                "max_tokens": 512,
            },
            model="gemini/gemini-2.0-flash",
        )
        assert out["model"] == "gemini-2.0-flash"
        # System message NOT in contents.
        assert all(
            m.get("role") != "system" for m in out["contents"]
        ), out["contents"]
        # System surfaced in config.systemInstruction.
        assert out["config"]["system_instruction"] == "You are helpful."
        # Tools wrapped under functionDeclarations.
        assert "tools" in out["config"]
        assert "function_declarations" in out["config"]["tools"][0]
        # tool_choice translated.
        assert out["config"]["tool_config"] == {
            "function_calling_config": {"mode": "AUTO"}
        }
        # Generation params translated.
        assert out["config"]["temperature"] == 0.3
        assert out["config"]["max_output_tokens"] == 512

    def test_system_extracted_to_config_not_contents(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [
                    {"role": "system", "content": "Be brief."},
                    {"role": "user", "content": "Hi"},
                ]
            },
            model="gemini/gemini-2.0-flash",
        )
        assert out["config"]["system_instruction"] == "Be brief."
        # Contents has only the user message.
        assert out["contents"] == [
            {"role": "user", "parts": [{"text": "Hi"}]}
        ]

    def test_max_tokens_explicit_none_is_dropped(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": None,
            },
            model="gemini/gemini-2.0-flash",
        )
        # Don't forward None to the SDK (Gemini rejects it).
        assert "max_output_tokens" not in out["config"]

    def test_max_completion_tokens_used_as_fallback(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "max_completion_tokens": 200,
            },
            model="gemini/gemini-2.0-flash",
        )
        assert out["config"]["max_output_tokens"] == 200

    def test_generation_params_translate_correctly(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "temperature": 0.5,
                "top_p": 0.9,
                "top_k": 40,
                "stop": ["END"],
                "seed": 42,
            },
            model="gemini/gemini-2.0-flash",
        )
        cfg = out["config"]
        assert cfg["temperature"] == 0.5
        assert cfg["top_p"] == 0.9
        assert cfg["top_k"] == 40
        assert cfg["stop_sequences"] == ["END"]
        assert cfg["seed"] == 42

    def test_response_format_json_schema_translates(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "Plan",
                        "schema": {"type": "object"},
                        "strict": True,
                    },
                },
            },
            model="gemini/gemini-2.0-flash",
        )
        assert out["config"]["response_mime_type"] == "application/json"
        assert out["config"]["response_schema"] == {"type": "object"}

    def test_response_schema_strips_camelcase_additional_properties(self):
        """Pydantic-generated schemas always emit
        ``additionalProperties: False`` (camelCase). Gemini rejects it
        with HTTP 400 INVALID_ARGUMENT — must be stripped from
        responseSchema (not just tool parameters)."""
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "Plan",
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"answer": {"type": "string"}},
                            "required": ["answer"],
                        },
                    },
                },
            },
            model="gemini/gemini-2.0-flash",
        )
        rs = out["config"]["response_schema"]
        assert "additionalProperties" not in rs
        assert rs["type"] == "object"
        assert rs["properties"] == {"answer": {"type": "string"}}
        assert rs["required"] == ["answer"]

    def test_response_schema_strips_snake_case_additional_properties(self):
        """Some upstream paths (Pydantic dump, LiteLLM normalization) emit
        ``additional_properties`` (snake_case). The whitelist sanitizer
        strips it because it's not in ``_GEMINI_SCHEMA_KEYS`` — verifies
        the snake_case variant doesn't slip past via responseSchema."""
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "Plan",
                        "schema": {
                            "type": "object",
                            "additional_properties": False,  # snake_case
                            "exclusive_minimum": 0,
                            "properties": {"answer": {"type": "string"}},
                        },
                    },
                },
            },
            model="gemini/gemini-2.0-flash",
        )
        rs = out["config"]["response_schema"]
        # Both casings dropped (only camelCase whitelist members survive).
        assert "additional_properties" not in rs
        assert "additionalProperties" not in rs
        assert "exclusive_minimum" not in rs
        assert rs["type"] == "object"

    def test_response_schema_strips_dollar_schema_and_title(self):
        """The whole rejected-key family (``$schema``, ``title``, ``$ref``,
        ``definitions``) must be stripped from response_schema too —
        same as for tool parameters."""
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "Plan",
                        "schema": {
                            "type": "object",
                            "title": "PlanSchema",
                            "$schema": "http://json-schema.org/draft-07/schema#",
                            "$ref": "#/definitions/Plan",
                            "definitions": {"Plan": {"type": "string"}},
                            "properties": {"answer": {"type": "string"}},
                        },
                    },
                },
            },
            model="gemini/gemini-2.0-flash",
        )
        rs = out["config"]["response_schema"]
        assert "title" not in rs
        assert "$schema" not in rs
        assert "$ref" not in rs
        assert "definitions" not in rs
        assert rs["type"] == "object"

    def test_drops_internal_mesh_sentinels(self):
        """``_mesh_*`` sentinels must NOT trigger a WARN — they're handled
        upstream in helpers._pop_mesh_*_flags."""
        gemini_native._logged_unsupported_kwargs.clear()
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "_mesh_hint_mode": True,
                "_mesh_hint_schema": {"type": "object"},
            },
            model="gemini/gemini-2.0-flash",
        )
        # No WARN logged for the _mesh_ keys.
        assert all(
            not k.startswith("_mesh_")
            for k in gemini_native._logged_unsupported_kwargs
        )


# ---------------------------------------------------------------------------
# Unsupported-kwarg WARN dedupe
# ---------------------------------------------------------------------------


class TestUnsupportedKwargWarn:
    @pytest.fixture(autouse=True)
    def _reset_dedupe(self):
        gemini_native._logged_unsupported_kwargs.clear()
        yield
        gemini_native._logged_unsupported_kwargs.clear()

    def test_warn_logs_for_unknown_kwarg(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            gemini_native._build_create_kwargs(
                {
                    "messages": [{"role": "user", "content": "Hi"}],
                    "request_timeout": 30,
                },
                model="gemini/gemini-2.0-flash",
            )
        warn_msgs = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert any(
            "request_timeout" in m and "dropping unsupported kwarg" in m
            for m in warn_msgs
        ), f"Expected WARN about request_timeout; got: {warn_msgs}"

    def test_warn_emits_only_once_per_key(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            gemini_native._warn_unsupported_kwarg_once("request_timeout")
            gemini_native._warn_unsupported_kwarg_once("request_timeout")
            gemini_native._warn_unsupported_kwarg_once("request_timeout")
        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "request_timeout" in r.getMessage()
        ]
        assert len(warns) == 1

    def test_warn_emits_once_per_unique_key(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            gemini_native._warn_unsupported_kwarg_once("a")
            gemini_native._warn_unsupported_kwarg_once("b")
            gemini_native._warn_unsupported_kwarg_once("a")
            gemini_native._warn_unsupported_kwarg_once("c")
        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert len(warns) == 3


# ---------------------------------------------------------------------------
# _adapt_response()
# ---------------------------------------------------------------------------


def _make_gemini_response(
    *,
    text: str | None = None,
    function_calls: list[dict] | None = None,
    prompt_tokens: int = 12,
    completion_tokens: int = 7,
    finish_reason: str = "STOP",
    model_version: str | None = "gemini-2.0-flash",
):
    """Build a fake genai.GenerateContentResponse-like object."""
    parts = []
    if text is not None:
        parts.append(SimpleNamespace(text=text, function_call=None))
    for fc in function_calls or []:
        parts.append(
            SimpleNamespace(
                text=None,
                function_call=SimpleNamespace(
                    name=fc["name"], args=fc.get("args", {})
                ),
            )
        )
    content = SimpleNamespace(parts=parts, role="model")
    fr_obj = SimpleNamespace(name=finish_reason)
    candidate = SimpleNamespace(content=content, finish_reason=fr_obj, index=0)
    usage = SimpleNamespace(
        prompt_token_count=prompt_tokens,
        candidates_token_count=completion_tokens,
        total_token_count=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(
        candidates=[candidate],
        usage_metadata=usage,
        model_version=model_version,
    )


class TestAdaptResponse:
    def test_text_only_response(self):
        raw = _make_gemini_response(text="Hello world", finish_reason="STOP")
        out = gemini_native._adapt_response(raw, model="gemini-2.0-flash")
        assert out.choices[0].message.content == "Hello world"
        assert out.choices[0].message.role == "assistant"
        assert out.choices[0].message.tool_calls is None
        assert out.choices[0].finish_reason == "stop"
        assert out.usage.prompt_tokens == 12
        assert out.usage.completion_tokens == 7
        assert out.model == "gemini-2.0-flash"

    def test_function_call_response_synthesizes_ids(self):
        raw = _make_gemini_response(
            function_calls=[
                {"name": "get_weather", "args": {"city": "NYC"}},
                {"name": "send_email", "args": {"to": "a@b"}},
            ],
            finish_reason="STOP",
        )
        out = gemini_native._adapt_response(raw, model="gemini-2.0-flash")
        tcs = out.choices[0].message.tool_calls
        assert len(tcs) == 2
        # Synthesized ids are sequential gemini_call_<index>.
        assert tcs[0].id == "gemini_call_0"
        assert tcs[1].id == "gemini_call_1"
        assert tcs[0].function.name == "get_weather"
        assert json.loads(tcs[0].function.arguments) == {"city": "NYC"}
        # Finish reason promoted to "tool_calls" when function calls present
        # (helpers.py expects this for the agentic loop to invoke tools).
        assert out.choices[0].finish_reason == "tool_calls"

    def test_mixed_text_and_function_calls(self):
        raw = _make_gemini_response(
            text="Calling weather...",
            function_calls=[{"name": "get_weather", "args": {"city": "NYC"}}],
        )
        out = gemini_native._adapt_response(raw, model="gemini-2.0-flash")
        assert out.choices[0].message.content == "Calling weather..."
        assert len(out.choices[0].message.tool_calls) == 1

    def test_usage_metadata_field_name_mapping(self):
        raw = _make_gemini_response(
            text="hi",
            prompt_tokens=100,
            completion_tokens=50,
        )
        out = gemini_native._adapt_response(raw, model="gemini-2.0-flash")
        # promptTokenCount → prompt_tokens; candidatesTokenCount → completion_tokens.
        assert out.usage.prompt_tokens == 100
        assert out.usage.completion_tokens == 50
        assert out.usage.total_tokens == 150

    def test_no_usage_does_not_crash(self):
        raw = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[SimpleNamespace(text="hi", function_call=None)]
                    ),
                    finish_reason=SimpleNamespace(name="STOP"),
                )
            ],
            usage_metadata=None,
            model_version="gemini-2.0-flash",
        )
        out = gemini_native._adapt_response(raw, model="gemini-2.0-flash")
        assert out.usage is None
        assert out.choices[0].message.content == "hi"

    def test_finish_reason_malformed_function_call_maps_to_tool_calls(self):
        """Recent google-genai versions emit MALFORMED_FUNCTION_CALL when the
        model attempted a tool call but produced invalid JSON. Map to
        ``tool_calls`` so helpers.py's agentic loop can surface the failure
        path naturally instead of treating it as a normal STOP."""
        raw = _make_gemini_response(
            text="garbled tool call",
            finish_reason="MALFORMED_FUNCTION_CALL",
        )
        out = gemini_native._adapt_response(raw, model="gemini-2.0-flash")
        assert out.choices[0].finish_reason == "tool_calls"


# ---------------------------------------------------------------------------
# complete() — request dispatch + adaptation
# ---------------------------------------------------------------------------


def _patched_genai_client(api_response, *, monkeypatch):
    """Return (cls_mock, generate_mock, instance_mock).

    Patches google.genai.Client so its instance has an
    ``.aio.models.generate_content`` AsyncMock returning ``api_response``.
    """
    instance = MagicMock()
    generate_mock = AsyncMock(return_value=api_response)
    instance.aio = MagicMock()
    instance.aio.models = MagicMock()
    instance.aio.models.generate_content = generate_mock
    cls_mock = MagicMock(return_value=instance)
    monkeypatch.setattr("google.genai.Client", cls_mock)
    return cls_mock, generate_mock, instance


class TestComplete:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")
        yield

    @pytest.mark.asyncio
    async def test_strips_model_prefix(self, monkeypatch):
        api_resp = _make_gemini_response(text="hi")
        cls_mock, generate_mock, _ = _patched_genai_client(
            api_resp, monkeypatch=monkeypatch
        )
        await gemini_native.complete(
            {"messages": [{"role": "user", "content": "Hi"}]},
            model="gemini/gemini-2.0-flash",
        )
        kwargs = generate_mock.call_args.kwargs
        assert kwargs["model"] == "gemini-2.0-flash"

    @pytest.mark.asyncio
    async def test_complete_returns_adapted_response(self, monkeypatch):
        api_resp = _make_gemini_response(
            text="Hello!", prompt_tokens=10, completion_tokens=3
        )
        _patched_genai_client(api_resp, monkeypatch=monkeypatch)
        out = await gemini_native.complete(
            {"messages": [{"role": "user", "content": "Hi"}]},
            model="gemini/gemini-2.0-flash",
        )
        assert out.choices[0].message.content == "Hello!"
        assert out.usage.prompt_tokens == 10
        assert out.usage.completion_tokens == 3


# ---------------------------------------------------------------------------
# complete_stream() — streaming chunks + best-effort usage
# ---------------------------------------------------------------------------


class _FakeAsyncStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def _gen():
            for c in self._chunks:
                yield c

        return _gen()


def _make_stream_chunk(
    *,
    text: str | None = None,
    function_call: dict | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
    model_version: str | None = None,
):
    """Build a fake genai streaming chunk."""
    parts = []
    if text is not None:
        parts.append(SimpleNamespace(text=text, function_call=None))
    if function_call is not None:
        parts.append(
            SimpleNamespace(
                text=None,
                function_call=SimpleNamespace(
                    name=function_call["name"],
                    args=function_call.get("args", {}),
                ),
            )
        )
    fr_obj = SimpleNamespace(name=finish_reason) if finish_reason else None
    candidates = []
    if parts or finish_reason:
        candidates.append(
            SimpleNamespace(
                content=SimpleNamespace(parts=parts, role="model")
                if parts
                else None,
                finish_reason=fr_obj,
                index=0,
            )
        )
    usage_obj = None
    if usage is not None:
        usage_obj = SimpleNamespace(
            prompt_token_count=usage.get("prompt_tokens", 0),
            candidates_token_count=usage.get("completion_tokens", 0),
            total_token_count=(
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            ),
        )
    return SimpleNamespace(
        candidates=candidates,
        usage_metadata=usage_obj,
        model_version=model_version,
    )


def _patched_streaming_genai(chunks, *, monkeypatch):
    instance = MagicMock()
    fake_stream = _FakeAsyncStream(chunks)
    instance.aio = MagicMock()
    instance.aio.models = MagicMock()
    instance.aio.models.generate_content_stream = AsyncMock(
        return_value=fake_stream
    )
    cls_mock = MagicMock(return_value=instance)
    monkeypatch.setattr("google.genai.Client", cls_mock)
    return cls_mock, instance


class TestCompleteStream:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")
        yield

    @pytest.mark.asyncio
    async def test_text_stream_yields_litellm_chunks(self, monkeypatch):
        chunks_in = [
            _make_stream_chunk(text="Hello ", model_version="gemini-2.0-flash"),
            _make_stream_chunk(text="world"),
            _make_stream_chunk(
                finish_reason="STOP",
                usage={"prompt_tokens": 10, "completion_tokens": 4},
            ),
        ]
        _patched_streaming_genai(chunks_in, monkeypatch=monkeypatch)

        stream = gemini_native.complete_stream(
            {"messages": [{"role": "user", "content": "Hi"}]},
            model="gemini/gemini-2.0-flash",
        )
        chunks = []
        async for c in stream:
            chunks.append(c)

        text_pieces = []
        for c in chunks:
            if c.choices:
                d = c.choices[0].delta
                if getattr(d, "content", None):
                    text_pieces.append(d.content)
        assert "".join(text_pieces) == "Hello world"

        # Final chunk carries usage.
        usage_chunks = [c for c in chunks if c.usage is not None]
        assert len(usage_chunks) == 1
        assert usage_chunks[0].usage.prompt_tokens == 10
        assert usage_chunks[0].usage.completion_tokens == 4

    @pytest.mark.asyncio
    async def test_function_call_stream_emits_synthesized_id(
        self, monkeypatch
    ):
        chunks_in = [
            _make_stream_chunk(
                function_call={
                    "name": "get_weather",
                    "args": {"city": "NYC"},
                },
                model_version="gemini-2.0-flash",
            ),
            _make_stream_chunk(
                finish_reason="STOP",
                usage={"prompt_tokens": 5, "completion_tokens": 2},
            ),
        ]
        _patched_streaming_genai(chunks_in, monkeypatch=monkeypatch)

        stream = gemini_native.complete_stream(
            {"messages": [{"role": "user", "content": "weather?"}]},
            model="gemini/gemini-2.0-flash",
        )
        chunks = []
        async for c in stream:
            chunks.append(c)

        # Find the chunk containing the tool_call delta.
        tc_chunks = [
            c for c in chunks
            if c.choices and c.choices[0].delta.tool_calls
        ]
        assert len(tc_chunks) == 1
        tc_delta = tc_chunks[0].choices[0].delta.tool_calls[0]
        assert tc_delta.id == "gemini_call_0"
        assert tc_delta.function.name == "get_weather"
        assert json.loads(tc_delta.function.arguments) == {"city": "NYC"}

    @pytest.mark.asyncio
    async def test_no_usage_chunk_when_stream_yields_no_usage(
        self, monkeypatch
    ):
        """If the stream ends without ever yielding usage_metadata, the
        finally block has nothing to fall back on (counters are 0) and
        must NOT emit a misleading 0-token usage chunk."""
        chunks_in = [
            _make_stream_chunk(text="Hello", model_version="gemini-2.0-flash"),
            _make_stream_chunk(finish_reason="STOP"),
        ]
        _patched_streaming_genai(chunks_in, monkeypatch=monkeypatch)

        stream = gemini_native.complete_stream(
            {"messages": [{"role": "user", "content": "Hi"}]},
            model="gemini/gemini-2.0-flash",
        )
        chunks = []
        async for c in stream:
            chunks.append(c)

        usage_chunks = [c for c in chunks if c.usage is not None]
        assert usage_chunks == []

    @pytest.mark.asyncio
    async def test_emits_best_effort_usage_when_stream_raises(
        self, monkeypatch
    ):
        """If the stream raises AFTER usage was observed and successfully
        yielded to the consumer, the finally block must NOT re-emit
        (final_usage_emitted is True)."""

        class _RaisingStream:
            def __init__(self, chunks):
                self._chunks = chunks

            def __aiter__(self):
                async def _gen():
                    for c in self._chunks:
                        if c == "RAISE":
                            raise RuntimeError("server cutoff")
                        yield c

                return _gen()

        chunks_in = [
            _make_stream_chunk(
                text="partial",
                usage={"prompt_tokens": 5, "completion_tokens": 1},
                model_version="gemini-2.0-flash",
            ),
            "RAISE",
        ]
        instance = MagicMock()
        instance.aio = MagicMock()
        instance.aio.models = MagicMock()
        instance.aio.models.generate_content_stream = AsyncMock(
            return_value=_RaisingStream(chunks_in)
        )
        cls_mock = MagicMock(return_value=instance)
        monkeypatch.setattr("google.genai.Client", cls_mock)

        stream = gemini_native.complete_stream(
            {"messages": [{"role": "user", "content": "Hi"}]},
            model="gemini/gemini-2.0-flash",
        )
        chunks = []
        raised = None
        try:
            async for c in stream:
                chunks.append(c)
        except RuntimeError as exc:
            raised = exc

        assert raised is not None and "server cutoff" in str(raised)
        # Single usage chunk delivered before the raise; finally must NOT
        # re-emit because final_usage_emitted was set True after the yield
        # returned.
        usage_chunks = [c for c in chunks if c.usage is not None]
        assert len(usage_chunks) == 1


# ---------------------------------------------------------------------------
# Shared httpx connection pool
# ---------------------------------------------------------------------------


class TestSharedHttpxClient:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        gemini_native._reset_shared_httpx_client()
        yield
        gemini_native._reset_shared_httpx_client()

    @pytest.mark.asyncio
    async def test_shared_httpx_client_reused_within_same_loop(
        self, monkeypatch
    ):
        """Two ``_build_client`` calls on the same event loop must reuse
        the same httpx pool — connection-pool reuse within a loop is the
        whole reason we cache."""
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)

        # Run inside an async context so _get_shared_httpx_client() picks
        # up the running loop and caches against it.
        async def _do_two_builds():
            gemini_native._build_client("gemini/gemini-2.0-flash", "GAK-A", None)
            gemini_native._build_client("gemini/gemini-2.0-flash", "GAK-B", None)

        await _do_two_builds()

        first_http = cls_mock.call_args_list[0].kwargs["http_options"].httpx_async_client
        second_http = cls_mock.call_args_list[1].kwargs["http_options"].httpx_async_client
        assert first_http is second_http

    def test_per_loop_httpx_pool_isolates_event_loops(self, monkeypatch):
        """Different event loops MUST get different httpx pool instances.

        This is the regression fix for the "asyncio.locks.Event ... is bound
        to a different event loop" bug — mesh's ``shared/tool_executor.py``
        round-robins tool calls across worker threads, each owning its own
        long-lived loop. A process-global ``httpx.AsyncClient`` would bind
        its anyio sync primitives to the first worker's loop and break the
        moment a call lands on a different worker.
        """
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")

        captured_clients: list = []

        async def _capture_client():
            captured_clients.append(gemini_native._get_shared_httpx_client())

        # Two distinct event loops. Each must produce its own httpx pool.
        loop_a = asyncio.new_event_loop()
        try:
            loop_a.run_until_complete(_capture_client())
        finally:
            loop_a.close()

        loop_b = asyncio.new_event_loop()
        try:
            loop_b.run_until_complete(_capture_client())
        finally:
            loop_b.close()

        assert len(captured_clients) == 2
        assert captured_clients[0] is not captured_clients[1], (
            "Same httpx.AsyncClient was reused across event loops — would "
            "trigger 'bound to a different event loop' RuntimeError on the "
            "second loop's first request"
        )

    def test_cross_loop_dispatch_does_not_raise(self, monkeypatch):
        """End-to-end: simulate the mesh worker-pool scenario — two
        ``complete()`` calls on two distinct event loops. The fix
        guarantees no cross-loop bug surfaces; without it the second
        loop's first request would raise.
        """
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")

        api_resp = _make_gemini_response(text="hi")

        def _fresh_genai_mock():
            instance = MagicMock()
            instance.aio = MagicMock()
            instance.aio.models = MagicMock()
            instance.aio.models.generate_content = AsyncMock(return_value=api_resp)
            return MagicMock(return_value=instance)

        cls_mock = _fresh_genai_mock()
        monkeypatch.setattr("google.genai.Client", cls_mock)

        async def _one_call():
            await gemini_native.complete(
                {"messages": [{"role": "user", "content": "hi"}]},
                model="gemini/gemini-2.0-flash",
            )

        loop_a = asyncio.new_event_loop()
        try:
            loop_a.run_until_complete(_one_call())
        finally:
            loop_a.close()

        loop_b = asyncio.new_event_loop()
        try:
            # Pre-fix: this raised "bound to a different event loop" if the
            # cached httpx pool was reused. Post-fix: each loop gets its
            # own pool from _get_shared_httpx_client.
            loop_b.run_until_complete(_one_call())
        finally:
            loop_b.close()

    def test_get_shared_httpx_returns_uncached_when_no_loop(self):
        """Sync test paths (no running loop) get an uncached client back —
        otherwise we'd cache against a nonexistent loop id."""
        c1 = gemini_native._get_shared_httpx_client()
        c2 = gemini_native._get_shared_httpx_client()
        # Each sync call returns a fresh client (not cached).
        assert c1 is not c2

    @pytest.mark.asyncio
    async def test_shared_httpx_client_recreated_after_close(self):
        first = gemini_native._get_shared_httpx_client()
        assert first.is_closed is False
        await first.aclose()
        assert first.is_closed is True
        second = gemini_native._get_shared_httpx_client()
        assert second is not first
        assert second.is_closed is False

    def test_lazy_per_call_client_construction(self, monkeypatch):
        """Two consecutive calls must build TWO genai.Client wrappers — the
        wrapper itself is NOT cached, so K8s secret rotation works."""
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")
        cls_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("google.genai.Client", cls_mock)
        gemini_native._build_client("gemini/gemini-2.0-flash", "GAK-A", None)
        gemini_native._build_client("gemini/gemini-2.0-flash", "GAK-B", None)
        assert cls_mock.call_count == 2
        # Second call has the rotated key.
        second_kwargs = cls_mock.call_args_list[1].kwargs
        assert second_kwargs["api_key"] == "GAK-B"


# ---------------------------------------------------------------------------
# Fallback-log helper getter
# ---------------------------------------------------------------------------


class TestIsFallbackLogged:
    def test_returns_false_initially_then_true_after_log(self, monkeypatch):
        monkeypatch.setattr(gemini_native, "_logged_fallback_once", False)
        assert gemini_native.is_fallback_logged() is False
        gemini_native.log_fallback_once()
        assert gemini_native.is_fallback_logged() is True

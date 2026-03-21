"""Unit tests for MeshLlmAgent media= parameter (Phase 3.3)."""

import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add the Python runtime source to the path so imports work outside tox
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "src" / "runtime" / "python")
)

from _mcp_mesh.media.resolver import _format_for_openai

# Shared test data
FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-data"
FAKE_PNG_B64 = base64.b64encode(FAKE_PNG_BYTES).decode("ascii")
FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-data"
FAKE_JPEG_B64 = base64.b64encode(FAKE_JPEG_BYTES).decode("ascii")


def _mock_media_store(side_effects=None, default_data=FAKE_PNG_BYTES, default_mime="image/png"):
    """Return a mock MediaStore.

    Args:
        side_effects: If provided, a list of (bytes, mime) tuples for successive fetch calls.
        default_data: Default bytes to return from fetch.
        default_mime: Default MIME type to return from fetch.
    """
    store = MagicMock()
    if side_effects:
        store.fetch = AsyncMock(side_effect=side_effects)
    else:
        store.fetch = AsyncMock(return_value=(default_data, default_mime))
    return store


def _make_agent():
    """Create a minimal MeshLlmAgent-like object for testing _resolve_media_inputs.

    We import and instantiate a real MeshLlmAgent but mock away everything
    except the method under test.
    """
    from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

    agent = MeshLlmAgent.__new__(MeshLlmAgent)
    return agent


# ---------------------------------------------------------------------------
# test: _resolve_media_inputs with URI strings
# ---------------------------------------------------------------------------
class TestResolveMediaInputsURI:
    @pytest.mark.asyncio
    async def test_single_uri_returns_image_block(self):
        agent = _make_agent()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs(["file:///tmp/photo.png"])

        assert len(parts) == 1
        part = parts[0]
        assert part["type"] == "image_url"
        assert part["image_url"]["url"] == f"data:image/png;base64,{FAKE_PNG_B64}"
        assert part["image_url"]["detail"] == "high"
        mock_store.fetch.assert_awaited_once_with("file:///tmp/photo.png")

    @pytest.mark.asyncio
    async def test_multiple_uris_return_multiple_blocks(self):
        agent = _make_agent()
        mock_store = _mock_media_store(
            side_effects=[
                (FAKE_PNG_BYTES, "image/png"),
                (FAKE_JPEG_BYTES, "image/jpeg"),
            ]
        )

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs([
                "file:///a.png",
                "s3://bucket/b.jpg",
            ])

        assert len(parts) == 2
        assert parts[0]["image_url"]["url"] == f"data:image/png;base64,{FAKE_PNG_B64}"
        assert parts[1]["image_url"]["url"] == f"data:image/jpeg;base64,{FAKE_JPEG_B64}"
        assert mock_store.fetch.await_count == 2


# ---------------------------------------------------------------------------
# test: _resolve_media_inputs with (bytes, mime_type) tuples
# ---------------------------------------------------------------------------
class TestResolveMediaInputsBytes:
    @pytest.mark.asyncio
    async def test_bytes_tuple_returns_image_block(self):
        agent = _make_agent()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs([
                (FAKE_PNG_BYTES, "image/png"),
            ])

        assert len(parts) == 1
        part = parts[0]
        assert part["type"] == "image_url"
        assert part["image_url"]["url"] == f"data:image/png;base64,{FAKE_PNG_B64}"
        # fetch should NOT be called for byte tuples
        mock_store.fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# test: _resolve_media_inputs with mixed input
# ---------------------------------------------------------------------------
class TestResolveMediaInputsMixed:
    @pytest.mark.asyncio
    async def test_mixed_uri_and_bytes(self):
        agent = _make_agent()
        mock_store = _mock_media_store(default_data=FAKE_JPEG_BYTES, default_mime="image/jpeg")

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs([
                "file:///remote.jpg",
                (FAKE_PNG_BYTES, "image/png"),
            ])

        assert len(parts) == 2
        # First: URI fetched as jpeg
        assert "image/jpeg" in parts[0]["image_url"]["url"]
        # Second: bytes tuple as png
        assert "image/png" in parts[1]["image_url"]["url"]


# ---------------------------------------------------------------------------
# test: _resolve_media_inputs gracefully skips errors
# ---------------------------------------------------------------------------
class TestResolveMediaInputsErrors:
    @pytest.mark.asyncio
    async def test_fetch_failure_skips_item(self):
        agent = _make_agent()
        mock_store = _mock_media_store()
        mock_store.fetch = AsyncMock(side_effect=FileNotFoundError("not found"))

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs(["file:///missing.png"])

        assert len(parts) == 0

    @pytest.mark.asyncio
    async def test_unsupported_type_skipped(self):
        agent = _make_agent()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs([12345, None])

        assert len(parts) == 0
        mock_store.fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_partial_failure_returns_successful(self):
        """One URI fails, another succeeds — only the successful one is returned."""
        agent = _make_agent()
        mock_store = _mock_media_store(
            side_effects=[
                FileNotFoundError("gone"),
                (FAKE_PNG_BYTES, "image/png"),
            ]
        )

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs([
                "file:///missing.png",
                "file:///ok.png",
            ])

        assert len(parts) == 1
        assert parts[0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# Helper: create a fully-mocked agent for __call__ tests
# ---------------------------------------------------------------------------
def _make_callable_agent():
    """Create a MeshLlmAgent with all dependencies mocked for __call__ testing."""
    from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

    agent = MeshLlmAgent.__new__(MeshLlmAgent)
    agent._iteration_count = 0
    agent.max_iterations = 1
    agent.model = "test-model"
    agent.output_type = str
    agent.output_mode = None
    agent._is_mesh_delegated = False
    agent._tool_schemas = []
    agent.tool_proxies = {}
    agent._default_model_params = {}
    agent._auto_context = {}
    agent._context_param_name = None
    agent.provider = None
    agent.api_key = "test-key"

    handler = MagicMock()
    handler.format_system_prompt.return_value = "system prompt"
    handler.prepare_request.side_effect = lambda messages, **kw: {
        "messages": messages,
        "model": "test-model",
    }
    agent._provider_handler = handler
    agent._resolve_context = MagicMock(return_value={})
    agent._render_system_prompt = MagicMock(return_value="system prompt")
    agent._parse_response = MagicMock(return_value="result")
    agent._attach_mesh_meta = MagicMock(return_value="result")

    return agent


def _make_mock_response():
    """Create a mock LiteLLM-like response."""
    mock_message = MagicMock()
    mock_message.content = "test response"
    mock_message.role = "assistant"
    mock_message.tool_calls = None
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None
    mock_response.model = None
    return mock_response


def _make_capturing_to_thread(mock_response):
    """Create an asyncio.to_thread replacement that captures the kwargs passed to the
    completion function and returns mock_response.

    Returns (async_mock, captured_kwargs_list).
    """
    captured = []

    async def fake_to_thread(func, **kwargs):
        captured.append(kwargs)
        return mock_response

    return fake_to_thread, captured


# ---------------------------------------------------------------------------
# test: __call__ message building — no media = backward compat
# ---------------------------------------------------------------------------
class TestCallNoMediaBackwardCompat:
    """When media=None (default), messages should be plain text, no multipart."""

    @pytest.mark.asyncio
    async def test_string_message_stays_plain_text(self):
        """Without media, user message content should be a plain string."""
        agent = _make_callable_agent()
        mock_response = _make_mock_response()
        fake_to_thread, captured = _make_capturing_to_thread(mock_response)

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.completion",
            MagicMock(),
        ):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                result = await agent("Hello, world!")

        assert len(captured) == 1
        messages = captured[0]["messages"]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "Hello, world!"
        assert isinstance(user_msgs[0]["content"], str)


# ---------------------------------------------------------------------------
# test: __call__ message building — media with string message
# ---------------------------------------------------------------------------
class TestCallMediaWithStringMessage:
    @pytest.mark.asyncio
    async def test_media_uri_builds_multipart_message(self):
        """With media=[uri], user message content should be [text, image_url]."""
        agent = _make_callable_agent()
        mock_response = _make_mock_response()
        fake_to_thread, captured = _make_capturing_to_thread(mock_response)
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.completion",
            MagicMock(),
        ):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch(
                    "_mcp_mesh.media.media_store.get_media_store",
                    return_value=mock_store,
                ):
                    result = await agent(
                        "Describe this image",
                        media=["file:///tmp/photo.png"],
                    )

        assert len(captured) == 1
        messages = captured[0]["messages"]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert len(user_msgs) == 1
        content = user_msgs[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "Describe this image"}
        assert content[1]["type"] == "image_url"
        assert f"data:image/png;base64,{FAKE_PNG_B64}" == content[1]["image_url"]["url"]


# ---------------------------------------------------------------------------
# test: __call__ message building — media with list[dict] message
# ---------------------------------------------------------------------------
class TestCallMediaWithListMessage:
    @pytest.mark.asyncio
    async def test_media_appended_to_last_user_message(self):
        """When message is list[dict] and media provided, media appends to last user msg."""
        agent = _make_callable_agent()
        mock_response = _make_mock_response()
        fake_to_thread, captured = _make_capturing_to_thread(mock_response)
        mock_store = _mock_media_store()

        conversation = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Now look at this image"},
        ]

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.completion",
            MagicMock(),
        ):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch(
                    "_mcp_mesh.media.media_store.get_media_store",
                    return_value=mock_store,
                ):
                    result = await agent(
                        conversation,
                        media=["file:///tmp/photo.png"],
                    )

        assert len(captured) == 1
        messages = captured[0]["messages"]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        last_user = user_msgs[-1]
        content = last_user["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "Now look at this image"}
        assert content[1]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_media_merged_with_existing_multipart_content(self):
        """If the last user message already has list content, media is appended."""
        agent = _make_callable_agent()
        mock_response = _make_mock_response()
        fake_to_thread, captured = _make_capturing_to_thread(mock_response)
        mock_store = _mock_media_store()

        existing_image = _format_for_openai(FAKE_JPEG_B64, "image/jpeg")
        conversation = [
            {"role": "user", "content": [
                {"type": "text", "text": "Look at both"},
                existing_image,
            ]},
        ]

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.completion",
            MagicMock(),
        ):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch(
                    "_mcp_mesh.media.media_store.get_media_store",
                    return_value=mock_store,
                ):
                    result = await agent(
                        conversation,
                        media=["file:///tmp/extra.png"],
                    )

        assert len(captured) == 1
        messages = captured[0]["messages"]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        last_user = user_msgs[-1]
        content = last_user["content"]
        assert isinstance(content, list)
        # Original text + original image + new media image = 3 items
        assert len(content) == 3
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"  # existing jpeg
        assert content[2]["type"] == "image_url"  # new png from media=


# ---------------------------------------------------------------------------
# test: multiple media items produce multiple image blocks
# ---------------------------------------------------------------------------
class TestMultipleMediaItems:
    @pytest.mark.asyncio
    async def test_two_uris_produce_two_image_blocks(self):
        agent = _make_agent()
        mock_store = _mock_media_store(
            side_effects=[
                (FAKE_PNG_BYTES, "image/png"),
                (FAKE_JPEG_BYTES, "image/jpeg"),
            ]
        )

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs([
                "file:///a.png",
                "file:///b.jpg",
            ])

        assert len(parts) == 2
        assert "image/png" in parts[0]["image_url"]["url"]
        assert "image/jpeg" in parts[1]["image_url"]["url"]

    @pytest.mark.asyncio
    async def test_bytes_tuple_returns_correct_image(self):
        agent = _make_agent()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.media_store.get_media_store",
            return_value=mock_store,
        ):
            parts = await agent._resolve_media_inputs([
                (FAKE_PNG_BYTES, "image/png"),
                (FAKE_JPEG_BYTES, "image/jpeg"),
            ])

        assert len(parts) == 2
        assert parts[0]["image_url"]["url"] == f"data:image/png;base64,{FAKE_PNG_B64}"
        assert parts[1]["image_url"]["url"] == f"data:image/jpeg;base64,{FAKE_JPEG_B64}"
        # No store.fetch calls for byte tuples
        mock_store.fetch.assert_not_awaited()

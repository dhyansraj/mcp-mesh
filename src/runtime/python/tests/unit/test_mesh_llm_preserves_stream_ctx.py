"""Unit tests for issue #645 bug 3: ``@mesh.llm`` must preserve the ``ctx``
parameter that ``@mesh.tool`` appended for streaming wrappers.

The decoration chain on a streaming LLM tool is:

    @app.tool()
    @mesh.llm(...)       # outer
    @mesh.tool(...)      # inner (runs first; the result is what @mesh.llm sees)
    async def chat(prompt: str, llm: MeshLlmAgent) -> mesh.Stream[str]: ...

``@mesh.tool`` builds a stream wrapper whose ``__signature__`` exposes
``ctx: Context | None = None`` so FastMCP auto-fills the progress context.
``@mesh.llm`` then strips its own ``llm`` parameter from the public signature
and used to start fresh from the original ``func`` — losing the appended
``ctx`` and silently disabling progress notifications.

After the fix, ``@mesh.llm`` reads from the wrapper's already-rebuilt
signature, so ``ctx`` survives the strip.
"""

# NOTE: do NOT add ``from __future__ import annotations`` — the @mesh.llm
# decorator's MeshLlmAgent detection compares param.annotation to the class
# directly. With PEP 563 annotations stay as strings, breaking detection.

import inspect

import pytest

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry


@pytest.fixture(autouse=True)
def _reset_decorator_registry():
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


class TestMeshLlmPreservesStreamCtx:
    def test_streaming_tool_with_mesh_llm_keeps_ctx_param(self):
        """Combined @mesh.llm + @mesh.tool + Stream[str] must keep ``ctx``."""

        @mesh.llm(
            provider={"capability": "llm"},
            max_iterations=1,
        )
        @mesh.tool(
            capability="chat-stream-test",
            description="streaming chat",
            version="1.0.0",
        )
        async def chat(
            prompt: str,
            llm: mesh.MeshLlmAgent = None,
        ) -> mesh.Stream[str]:
            yield prompt

        sig = inspect.signature(chat)

        # The ``llm`` injectable must be hidden from FastMCP's schema.
        assert "llm" not in sig.parameters
        # The ``prompt`` user-facing param must remain.
        assert "prompt" in sig.parameters
        # The ``ctx`` keyword that @mesh.tool's stream wrapper appended for
        # FastMCP's progress-handler auto-fill MUST survive @mesh.llm's strip.
        assert "ctx" in sig.parameters, (
            "ctx parameter dropped by @mesh.llm — progress notifications will "
            "no-op. See issue #645 bug 3."
        )
        ctx_param = sig.parameters["ctx"]
        assert ctx_param.kind == inspect.Parameter.KEYWORD_ONLY
        assert ctx_param.default is None

    def test_non_streaming_tool_with_mesh_llm_does_not_invent_ctx(self):
        """No Stream[str] return → no ``ctx`` should appear in the signature."""

        @mesh.llm(
            provider={"capability": "llm"},
            max_iterations=1,
        )
        @mesh.tool(
            capability="chat-buffered-test",
            description="buffered chat",
            version="1.0.0",
        )
        async def chat(
            prompt: str,
            llm: mesh.MeshLlmAgent = None,
        ) -> str:
            return prompt

        sig = inspect.signature(chat)
        assert "llm" not in sig.parameters
        assert "prompt" in sig.parameters
        # No streaming → @mesh.tool didn't append ctx → it stays absent.
        assert "ctx" not in sig.parameters

    def test_mesh_llm_stream_str_normalizes_output_type_to_str(self):
        """``Stream[str]`` return must register output_type=str.

        ``MeshLlmAgent.stream()`` rejects any output_type other than ``str``.
        The decorator extracts output_type from the raw return annotation,
        which for a streaming tool is ``AsyncIterator[str]``. Without
        normalization the rejection fires for every real-LLM streaming tool —
        the bug stayed silent because unit tests pass output_type=str directly
        and dry-run paths never hit ``stream()``.
        """

        @mesh.llm(provider="claude", model="anthropic/claude-sonnet-4-5")
        @mesh.tool(capability="chat-stream-output-type-test")
        async def chat(
            prompt: str,
            llm: mesh.MeshLlmAgent = None,
        ) -> mesh.Stream[str]:
            yield prompt

        agents = DecoratorRegistry.get_mesh_llm_agents()
        chat_agents = [
            a for a in agents.values() if a.function.__name__ == "chat"
        ]
        assert len(chat_agents) == 1
        assert chat_agents[0].output_type is str

    def test_mesh_llm_only_stream_str_normalizes_output_type_to_str(self):
        """Same normalization without a ``@mesh.tool`` layer underneath."""

        @mesh.llm(provider="claude", model="anthropic/claude-sonnet-4-5")
        async def chat(
            prompt: str,
            llm: mesh.MeshLlmAgent = None,
        ) -> mesh.Stream[str]:
            yield prompt

        agents = DecoratorRegistry.get_mesh_llm_agents()
        chat_agents = [
            a for a in agents.values() if a.function.__name__ == "chat"
        ]
        assert len(chat_agents) == 1
        assert chat_agents[0].output_type is str

    def test_mesh_llm_pydantic_output_type_preserved(self):
        """Non-streaming Pydantic return must still be preserved verbatim."""
        from pydantic import BaseModel

        class Reply(BaseModel):
            text: str

        @mesh.llm(provider="claude", model="anthropic/claude-sonnet-4-5")
        async def chat(
            prompt: str,
            llm: mesh.MeshLlmAgent = None,
        ) -> Reply:
            return Reply(text=prompt)

        agents = DecoratorRegistry.get_mesh_llm_agents()
        chat_agents = [
            a for a in agents.values() if a.function.__name__ == "chat"
        ]
        assert len(chat_agents) == 1
        assert chat_agents[0].output_type is Reply

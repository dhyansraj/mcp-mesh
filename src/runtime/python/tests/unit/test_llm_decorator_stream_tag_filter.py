"""Unit tests for the consumer-side ``ai.mcpmesh.stream`` tag augmentation.

Phase 5C of the mesh-delegate streaming work for issue #849.

The ``@mesh.llm`` decorator inspects the consumer function's return type and
augments the ``provider["tags"]`` filter that gets sent to the registry
resolver:
  * ``Stream[str]`` → append ``ai.mcpmesh.stream`` (required match — only the
    streaming variant of the provider matches).
  * Anything else (``str``, Pydantic model, etc.) → append ``-ai.mcpmesh.stream``
    (excluded — only the buffered variant matches).

The producer half of the contract is in ``@mesh.llm_provider``: the auto-
generated ``process_chat_stream`` carries ``ai.mcpmesh.stream``; the buffered
``process_chat`` does not. The registry's existing +/- tag-operator semantics
do the rest — no resolver special-casing.
"""

import pytest
from pydantic import BaseModel

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry


def _provider_config(agent_data) -> dict:
    """Helper to extract the resolved provider dict from registered metadata."""
    provider = agent_data.config["provider"]
    assert isinstance(provider, dict), (
        f"Expected provider dict, got {type(provider).__name__}: {provider!r}"
    )
    return provider


class _ChatResponse(BaseModel):
    answer: str
    confidence: float


class TestStreamTagAugmentation:
    """Consumer-side tag augmentation based on return type."""

    def setup_method(self):
        DecoratorRegistry._mesh_llm_agents = {}

    def test_stream_return_adds_required_tag(self):
        """``Stream[str]`` return type → ``ai.mcpmesh.stream`` (required) appended."""

        @mesh.llm(provider={"capability": "llm", "tags": ["existing"]})
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> mesh.Stream[str]:
            async for chunk in llm.stream(message):
                yield chunk

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        provider = _provider_config(agent_data)

        assert provider["capability"] == "llm"
        assert provider["tags"] == ["existing", "ai.mcpmesh.stream"]

    def test_buffered_return_adds_excluded_tag(self):
        """``str`` return type → ``-ai.mcpmesh.stream`` (excluded) appended."""

        @mesh.llm(provider={"capability": "llm", "tags": ["existing"]})
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
            return await llm(message)

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        provider = _provider_config(agent_data)

        assert provider["tags"] == ["existing", "-ai.mcpmesh.stream"]

    def test_pydantic_return_adds_excluded_tag(self):
        """Pydantic-model return → buffered → ``-ai.mcpmesh.stream``."""

        @mesh.llm(provider={"capability": "llm", "tags": ["existing"]})
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> _ChatResponse:
            return await llm(message)

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        provider = _provider_config(agent_data)

        assert provider["tags"] == ["existing", "-ai.mcpmesh.stream"]

    def test_explicit_user_required_tag_respected(self):
        """User-supplied ``ai.mcpmesh.stream`` (required) is preserved verbatim."""

        @mesh.llm(provider={"capability": "llm", "tags": ["ai.mcpmesh.stream"]})
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
            # Buffered return type, but user explicitly asked for streaming
            # provider — don't fight them.
            return await llm(message)

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        provider = _provider_config(agent_data)

        assert provider["tags"] == ["ai.mcpmesh.stream"]

    def test_explicit_user_preferred_tag_respected(self):
        """User-supplied ``+ai.mcpmesh.stream`` (preferred) is preserved verbatim."""

        @mesh.llm(provider={"capability": "llm", "tags": ["+ai.mcpmesh.stream"]})
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> mesh.Stream[str]:
            async for chunk in llm.stream(message):
                yield chunk

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        provider = _provider_config(agent_data)

        assert provider["tags"] == ["+ai.mcpmesh.stream"]

    def test_explicit_user_excluded_tag_respected(self):
        """User-supplied ``-ai.mcpmesh.stream`` (excluded) is preserved verbatim."""

        @mesh.llm(provider={"capability": "llm", "tags": ["-ai.mcpmesh.stream"]})
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> mesh.Stream[str]:
            async for chunk in llm.stream(message):
                yield chunk

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        provider = _provider_config(agent_data)

        assert provider["tags"] == ["-ai.mcpmesh.stream"]

    def test_no_provider_dict_no_tag_change(self):
        """Direct mode (string provider) — no augmentation, provider stays a string."""

        @mesh.llm(provider="claude")
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
            return await llm(message)

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        assert agent_data.config["provider"] == "claude"

    def test_provider_dict_without_user_tags(self):
        """Provider dict with no ``tags`` key gets a fresh single-tag list."""

        @mesh.llm(provider={"capability": "llm"})
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
            return await llm(message)

        agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(agents.values()))
        provider = _provider_config(agent_data)

        assert provider["tags"] == ["-ai.mcpmesh.stream"]

    def test_user_provider_dict_not_mutated(self):
        """The user's provider dict must not be mutated in place."""

        user_provider = {"capability": "llm", "tags": ["existing"]}
        original_tags = user_provider["tags"]

        @mesh.llm(provider=user_provider)
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
            return await llm(message)

        # The user's dict is untouched: same list object, same contents.
        assert user_provider["tags"] is original_tags
        assert user_provider["tags"] == ["existing"]

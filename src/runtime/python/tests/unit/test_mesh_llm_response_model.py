"""
Unit tests for @mesh.llm `response_model=` kwarg (issue #1085).

`response_model` lets the LLM-emitted/validated schema be specified separately
from the function's return annotation. The return annotation independently drives
the tool `outputSchema`.
"""

import warnings

import pytest
from pydantic import BaseModel

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor


class SmallModel(BaseModel):
    """The schema the LLM is asked to emit."""

    summary: str


class BigModel(BaseModel):
    """The full tool result type (return annotation)."""

    summary: str
    email: str
    total: float


class TestMeshLlmResponseModel:
    """Test response_model precedence over the return annotation."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_response_model_overrides_return_annotation_for_output_type(self):
        """response_model drives the LLM output_type, return annotation drives outputSchema."""

        @mesh.llm(
            provider={"capability": "llm"},
            filter={"capability": "document"},
            response_model=SmallModel,
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> BigModel:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        # LLM-emitted/validated schema is response_model, NOT the return
        # annotation — guard against silent precedence inversion.
        assert agent_data.output_type is SmallModel
        assert agent_data.output_type is not BigModel

        # Tool outputSchema is extracted INDEPENDENTLY from the return annotation.
        output_schema = FastMCPSchemaExtractor.extract_output_schema(
            agent_data.function
        )
        big_schema = BigModel.model_json_schema()
        assert set(output_schema["properties"].keys()) == set(
            big_schema["properties"].keys()
        )
        assert "email" in output_schema["properties"]
        assert "total" in output_schema["properties"]

    def test_text_streaming_overrides_response_model_output_type(self):
        """A text-streaming tool collapses output_type to str even when
        response_model is set — the streaming override wins.

        ``Stream[str]`` is a string-typed contract (str chunks accumulating to a
        str result); ``MeshLlmAgent.stream()`` rejects any other output_type.
        So response_model is intentionally discarded for text streams.
        """

        @mesh.llm(
            provider={"capability": "llm"},
            filter={"capability": "document"},
            response_model=SmallModel,
        )
        async def chat(
            message: str, llm: mesh.MeshLlmAgent = None
        ) -> mesh.Stream[str]:
            yield message

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.output_type is str
        assert agent_data.output_type is not SmallModel

    def test_no_response_model_falls_back_to_return_annotation(self):
        """Without response_model, output_type == return annotation (back-compat)."""

        @mesh.llm(
            provider={"capability": "llm"},
            filter={"capability": "document"},
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> BigModel:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.output_type is BigModel

    def test_response_model_not_forwarded_to_provider_params(self):
        """response_model is consumed as the LLM output type, not passed through
        as a provider model param.

        Extra **kwargs (genuine model params like ``temperature``) land in the
        resolved config that is forwarded to the provider. ``response_model`` is
        a named decorator kwarg with a dedicated meaning, so it must NOT appear
        in that passthrough — it must instead drive the resolved ``output_type``.
        Asserting against the same dict that a real model param lands in proves
        the exclusion is real, not structural.
        """

        @mesh.llm(
            provider={"capability": "llm"},
            filter={"capability": "document"},
            response_model=SmallModel,
            temperature=0.7,
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> BigModel:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        # A genuine model param IS forwarded to the provider via the config.
        assert agent_data.config.get("temperature") == 0.7
        # response_model is NOT forwarded as a provider model param...
        assert "response_model" not in agent_data.config
        # ...it is consumed as the resolved LLM output type instead.
        assert agent_data.output_type is SmallModel

    def test_non_basemodel_response_model_warns(self):
        """A response_model that isn't a BaseModel triggers the BaseModel warning."""

        with pytest.warns(UserWarning, match="should return a Pydantic BaseModel"):

            @mesh.llm(
                provider={"capability": "llm"},
                filter={"capability": "document"},
                response_model=dict,
            )
            def chat(message: str, llm: mesh.MeshLlmAgent = None) -> BigModel:
                return llm(message)

    def test_basemodel_response_model_with_nonllm_return_does_not_warn(self):
        """response_model=BaseModel + non-BaseModel return annotation should NOT warn."""

        with warnings.catch_warnings():
            warnings.simplefilter("error")

            @mesh.llm(
                provider={"capability": "llm"},
                filter={"capability": "document"},
                response_model=SmallModel,
            )
            def chat(message: str, llm: mesh.MeshLlmAgent = None) -> dict:
                return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.output_type is SmallModel

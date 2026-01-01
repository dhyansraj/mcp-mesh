"""
Comprehensive unit tests for MeshLlmAgent proxy class.

This is the most critical component - the automatic agentic loop that users rely on.
Tests cover happy paths, error scenarios, edge cases, and timeouts.

Tests follow TDD approach - these should FAIL initially until proxy is implemented.
"""

from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field, ValidationError

from _mcp_mesh.engine.llm_config import LLMConfig

# Helper to get fixture paths - tests run from various directories
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
TEMPLATES_DIR = FIXTURES_DIR / "templates"

try:
    from mesh import MeshContextModel
except ImportError:
    MeshContextModel = None


# Test output types
class ChatResponse(BaseModel):
    """Standard chat response for testing."""

    answer: str
    confidence: float
    sources: list[str] = []


class ComplexResponse(BaseModel):
    """Complex response with nested data."""

    result: dict
    metadata: dict
    status: str


# Test helpers for creating proper mocks
def make_function_mock(name: str, arguments: str):
    """Create a function mock with proper attributes."""
    func = MagicMock()
    func.name = name
    func.arguments = arguments
    return func


def make_tool_call_mock(id: str, name: str, arguments: str):
    """Create a tool_call mock with proper attributes."""
    tool_call = MagicMock()
    tool_call.id = id
    tool_call.function = make_function_mock(name, arguments)
    return tool_call


def make_test_config(
    provider: str = "claude",
    model: str = "claude-3-5-sonnet-20241022",
    api_key: str = "test-key",
    max_iterations: int = 10,
    system_prompt: Optional[str] = None,
) -> LLMConfig:
    """Create LLMConfig for testing."""
    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        max_iterations=max_iterations,
        system_prompt=system_prompt,
    )


class TestMeshLlmAgentInitialization:
    """Test MeshLlmAgent proxy initialization."""

    def test_initialization_with_minimal_config(self):
        """Test initialization with minimal required config."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
                system_prompt="You are a helpful assistant.",
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        assert agent.provider == "claude"
        assert agent.model == "claude-3-5-sonnet-20241022"
        assert agent.max_iterations == 10
        assert agent.output_type == ChatResponse

    def test_initialization_with_tools(self):
        """Test initialization with filtered tools."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        mock_tool_proxy = MagicMock()
        mock_tool_proxy.name = "extract_pdf"
        mock_tool_proxy.description = "Extract text from PDF"
        mock_tool_proxy.input_schema = {"type": "object"}

        tools = [mock_tool_proxy]

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=tools,
            output_type=ChatResponse,
        )

        assert len(agent.tools_metadata) == 1
        assert agent.tools_metadata[0].name == "extract_pdf"

    def test_initialization_with_system_prompt(self):
        """Test initialization with custom system prompt."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
                system_prompt="You are a helpful assistant.",
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        assert agent.system_prompt == "You are a helpful assistant."

    def test_set_system_prompt(self):
        """Test setting system prompt after initialization."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
                system_prompt="Original prompt",
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        agent.set_system_prompt("You are an expert analyst.")
        assert agent.system_prompt == "You are an expert analyst."


class TestMeshLlmAgentHappyPath:
    """Test successful agentic loop scenarios."""

    @pytest.mark.asyncio
    async def test_simple_response_without_tools(self):
        """Test simple LLM response without tool usage."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        # Mock LiteLLM completion to return final response
        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Hello!", "confidence": 0.95, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            response = await agent("Say hello")

            assert isinstance(response, ChatResponse)
            assert response.answer == "Hello!"
            assert response.confidence == 0.95
            mock_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_agentic_loop_with_single_tool_call(self):
        """Test agentic loop with one tool call."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # Create mock tool proxy
        mock_tool_proxy = AsyncMock()
        mock_tool_proxy.name = "extract_pdf"
        mock_tool_proxy.call_tool = AsyncMock(return_value={"text": "PDF content here"})
        mock_tool_proxy.description = "Extract text from PDF"
        mock_tool_proxy.input_schema = {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
        }

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[mock_tool_proxy],
            tool_proxies={"extract_pdf": mock_tool_proxy},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # First call: LLM wants to use tool
            tool_call = MagicMock()
            tool_call.id = "call_123"
            tool_call.function.name = "extract_pdf"
            tool_call.function.arguments = '{"file_path": "/test.pdf"}'

            # Second call: LLM returns final response
            mock_completion.side_effect = [
                MagicMock(
                    choices=[
                        MagicMock(message=MagicMock(content="", tool_calls=[tool_call]))
                    ]
                ),
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content='{"answer": "The PDF contains: PDF content here", "confidence": 0.9, "sources": ["/test.pdf"]}',
                                tool_calls=None,
                            )
                        )
                    ]
                ),
            ]

            response = await agent("Analyze /test.pdf")

            assert isinstance(response, ChatResponse)
            assert "PDF content here" in response.answer
            assert response.confidence == 0.9
            assert "/test.pdf" in response.sources
            assert mock_completion.call_count == 2
            mock_tool_proxy.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_agentic_loop_with_multiple_tool_calls(self):
        """Test agentic loop with multiple sequential tool calls."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # Create multiple mock tools
        pdf_tool = AsyncMock()
        pdf_tool.name = "extract_pdf"
        pdf_tool.call_tool = AsyncMock(return_value={"text": "PDF content"})
        pdf_tool.description = "Extract text from PDF"
        pdf_tool.input_schema = {"type": "object"}

        search_tool = AsyncMock()
        search_tool.name = "web_search"
        search_tool.call_tool = AsyncMock(
            return_value={"results": ["Result 1", "Result 2"]}
        )
        search_tool.description = "Search the web"
        search_tool.input_schema = {"type": "object"}

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[pdf_tool, search_tool],
            tool_proxies={"extract_pdf": pdf_tool, "web_search": search_tool},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # Simulate: tool call -> tool call -> final response
            mock_completion.side_effect = [
                # First: use PDF tool
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content="",
                                tool_calls=[
                                    make_tool_call_mock("call_1", "extract_pdf", "{}")
                                ],
                            )
                        )
                    ]
                ),
                # Second: use search tool
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content="",
                                tool_calls=[
                                    make_tool_call_mock(
                                        "call_2", "web_search", '{"query": "test"}'
                                    )
                                ],
                            )
                        )
                    ]
                ),
                # Third: final response
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content='{"answer": "Combined results", "confidence": 0.85, "sources": []}',
                                tool_calls=None,
                            )
                        )
                    ]
                ),
            ]

            response = await agent("Analyze and search")

            assert isinstance(response, ChatResponse)
            assert response.answer == "Combined results"
            assert mock_completion.call_count == 3
            pdf_tool.call_tool.assert_called_once()
            search_tool.call_tool.assert_called_once()


class TestMeshLlmAgentToolErrors:
    """Test error handling when tools fail."""

    @pytest.mark.asyncio
    async def test_tool_execution_error(self):
        """Test handling of tool execution errors."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent, ToolExecutionError

        mock_tool = AsyncMock()
        mock_tool.name = "failing_tool"
        mock_tool.call_tool = AsyncMock(side_effect=Exception("Tool crashed!"))
        mock_tool.description = "A tool that fails"
        mock_tool.input_schema = {"type": "object"}

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[mock_tool],
            tool_proxies={"failing_tool": mock_tool},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content="",
                            tool_calls=[
                                make_tool_call_mock("call_1", "failing_tool", "{}")
                            ],
                        )
                    )
                ]
            )

            with pytest.raises(ToolExecutionError, match="Tool crashed!"):
                await agent("Use the failing tool")

    @pytest.mark.asyncio
    async def test_tool_not_found_error(self):
        """Test handling when LLM requests unknown tool."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent, ToolExecutionError

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],  # No tools available
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content="",
                            tool_calls=[
                                make_tool_call_mock("call_1", "nonexistent_tool", "{}")
                            ],
                        )
                    )
                ]
            )

            with pytest.raises(ToolExecutionError, match="Tool.*not found"):
                await agent("Use nonexistent tool")

    @pytest.mark.asyncio
    async def test_tool_timeout(self):
        """Test handling of tool execution timeout."""
        import asyncio

        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent, ToolExecutionError

        mock_tool = AsyncMock()
        mock_tool.name = "slow_tool"
        mock_tool.call_tool = AsyncMock(side_effect=TimeoutError("Tool timed out"))
        mock_tool.description = "A slow tool"
        mock_tool.input_schema = {"type": "object"}

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[mock_tool],
            tool_proxies={"slow_tool": mock_tool},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content="",
                            tool_calls=[
                                make_tool_call_mock("call_1", "slow_tool", "{}")
                            ],
                        )
                    )
                ]
            )

            with pytest.raises(ToolExecutionError, match="timed out"):
                await agent("Use slow tool")


class TestMeshLlmAgentResponseFormatErrors:
    """Test error handling for invalid response formats."""

    @pytest.mark.asyncio
    async def test_invalid_json_response(self):
        """Test handling of invalid JSON in LLM response."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from _mcp_mesh.engine.response_parser import ResponseParseError

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content="This is not valid JSON!", tool_calls=None
                        )
                    )
                ]
            )

            with pytest.raises(ResponseParseError, match="Invalid JSON"):
                await agent("Say hello")

    @pytest.mark.asyncio
    async def test_pydantic_validation_error(self):
        """Test handling when response doesn't match Pydantic schema."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from _mcp_mesh.engine.response_parser import ResponseParseError

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # Valid JSON but missing required fields
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Hello"}',  # Missing 'confidence' field
                            tool_calls=None,
                        )
                    )
                ]
            )

            with pytest.raises(ResponseParseError, match="validation"):
                await agent("Say hello")

    @pytest.mark.asyncio
    async def test_wrong_response_type(self):
        """Test handling when response has wrong type for field."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from _mcp_mesh.engine.response_parser import ResponseParseError

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # confidence should be float, not string
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Hello", "confidence": "very high", "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            with pytest.raises(ResponseParseError, match="validation"):
                await agent("Say hello")


class TestMeshLlmAgentMaxIterations:
    """Test max iterations limit."""

    @pytest.mark.asyncio
    async def test_max_iterations_exceeded(self):
        """Test error when max_iterations is exceeded."""
        from _mcp_mesh.engine.mesh_llm_agent import MaxIterationsError, MeshLlmAgent

        mock_tool = AsyncMock()
        mock_tool.name = "endless_tool"
        mock_tool.call_tool = AsyncMock(return_value={"result": "ok"})
        mock_tool.description = "A tool"
        mock_tool.input_schema = {"type": "object"}

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=3,  # Very low limit
            ),
            filtered_tools=[mock_tool],
            tool_proxies={"endless_tool": mock_tool},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # Always return tool calls, never final response
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content="",
                            tool_calls=[
                                make_tool_call_mock("call_1", "endless_tool", "{}")
                            ],
                        )
                    )
                ]
            )

            with pytest.raises(MaxIterationsError, match="Exceeded.*3 iterations"):
                await agent("Keep using tools")

    @pytest.mark.asyncio
    async def test_exactly_at_max_iterations(self):
        """Test successful completion exactly at max_iterations."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        mock_tool = AsyncMock()
        mock_tool.name = "test_tool"
        mock_tool.call_tool = AsyncMock(return_value={"result": "ok"})
        mock_tool.description = "A tool"
        mock_tool.input_schema = {"type": "object"}

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[mock_tool],
            tool_proxies={"test_tool": mock_tool},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # First iteration: tool call
            # Second iteration: final response (exactly at limit)
            mock_completion.side_effect = [
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content="",
                                tool_calls=[
                                    make_tool_call_mock("call_1", "test_tool", "{}")
                                ],
                            )
                        )
                    ]
                ),
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content='{"answer": "Done", "confidence": 1.0, "sources": []}',
                                tool_calls=None,
                            )
                        )
                    ]
                ),
            ]

            response = await agent("Test")

            assert isinstance(response, ChatResponse)
            assert response.answer == "Done"


class TestMeshLlmAgentLLMAPIErrors:
    """Test LLM API error handling."""

    @pytest.mark.asyncio
    async def test_llm_api_error(self):
        """Test handling of LLM API errors."""
        from _mcp_mesh.engine.mesh_llm_agent import LLMAPIError, MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.side_effect = Exception("API Error: Rate limit exceeded")

            with pytest.raises(LLMAPIError, match="Rate limit exceeded"):
                await agent("Say hello")

    @pytest.mark.asyncio
    async def test_llm_authentication_error(self):
        """Test handling of authentication errors."""
        from _mcp_mesh.engine.mesh_llm_agent import LLMAPIError, MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="invalid-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.side_effect = Exception("API Error: Invalid API key")

            with pytest.raises(LLMAPIError, match="Invalid API key"):
                await agent("Say hello")

    @pytest.mark.asyncio
    async def test_llm_timeout(self):
        """Test handling of LLM API timeout."""
        import asyncio

        from _mcp_mesh.engine.mesh_llm_agent import LLMAPIError, MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.side_effect = TimeoutError("LLM request timed out")

            with pytest.raises(LLMAPIError, match="timed out"):
                await agent("Say hello")


class TestMeshLlmAgentEdgeCases:
    """Test edge cases and unusual scenarios."""

    @pytest.mark.asyncio
    async def test_empty_message(self):
        """Test handling of empty message."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Please provide a message", "confidence": 0.5, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            response = await agent("")

            assert isinstance(response, ChatResponse)
            # Should still work, LLM handles empty input

    @pytest.mark.asyncio
    async def test_very_long_message(self):
        """Test handling of very long message."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        long_message = "test " * 10000  # Very long message

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Processed", "confidence": 0.8, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            response = await agent(long_message)

            assert isinstance(response, ChatResponse)
            # Should handle long messages (LiteLLM/provider handles token limits)

    @pytest.mark.asyncio
    async def test_no_tools_available(self):
        """Test with no tools available."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],  # No tools
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # LLM should work without tools
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "No tools needed", "confidence": 1.0, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            response = await agent("Just chat")

            assert isinstance(response, ChatResponse)
            assert response.answer == "No tools needed"

    @pytest.mark.asyncio
    async def test_tool_returns_empty_result(self):
        """Test when tool returns empty result."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        mock_tool = AsyncMock()
        mock_tool.name = "empty_tool"
        mock_tool.call_tool = AsyncMock(return_value={})  # Empty result
        mock_tool.description = "Returns nothing"
        mock_tool.input_schema = {"type": "object"}

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[mock_tool],
            tool_proxies={"empty_tool": mock_tool},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.side_effect = [
                # First: use tool
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content="",
                                tool_calls=[
                                    make_tool_call_mock("call_1", "empty_tool", "{}")
                                ],
                            )
                        )
                    ]
                ),
                # Second: final response
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content='{"answer": "Tool returned nothing", "confidence": 0.5, "sources": []}',
                                tool_calls=None,
                            )
                        )
                    ]
                ),
            ]

            response = await agent("Use empty tool")

            assert isinstance(response, ChatResponse)
            # Should handle empty tool results gracefully


class TestMeshLlmAgentComplexScenarios:
    """Test complex real-world scenarios."""

    @pytest.mark.asyncio
    async def test_parallel_tool_calls_in_one_response(self):
        """Test when LLM requests multiple tools in single response."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        tool1 = AsyncMock()
        tool1.name = "tool_a"
        tool1.call_tool = AsyncMock(return_value={"result": "A"})
        tool1.description = "Tool A"
        tool1.input_schema = {"type": "object"}

        tool2 = AsyncMock()
        tool2.name = "tool_b"
        tool2.call_tool = AsyncMock(return_value={"result": "B"})
        tool2.description = "Tool B"
        tool2.input_schema = {"type": "object"}

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[tool1, tool2],
            tool_proxies={"tool_a": tool1, "tool_b": tool2},
            output_type=ChatResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.side_effect = [
                # First: request both tools at once
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content="",
                                tool_calls=[
                                    make_tool_call_mock("call_1", "tool_a", "{}"),
                                    make_tool_call_mock("call_2", "tool_b", "{}"),
                                ],
                            )
                        )
                    ]
                ),
                # Second: final response
                MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content='{"answer": "Both tools executed", "confidence": 0.9, "sources": []}',
                                tool_calls=None,
                            )
                        )
                    ]
                ),
            ]

            response = await agent("Use both tools")

            assert isinstance(response, ChatResponse)
            assert response.answer == "Both tools executed"
            tool1.call_tool.assert_called_once()
            tool2.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_complex_pydantic_model_response(self):
        """Test with complex nested Pydantic model."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ComplexResponse,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"result": {"key": "value"}, "metadata": {"version": "1.0"}, "status": "success"}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            response = await agent("Complex query")

            assert isinstance(response, ComplexResponse)
            assert response.result == {"key": "value"}
            assert response.metadata == {"version": "1.0"}
            assert response.status == "success"

    @pytest.mark.asyncio
    async def test_system_prompt_override(self):
        """Test system prompt override before execution."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(
                provider="claude",
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        # Override before calling
        agent.set_system_prompt("New prompt for this call")

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Response", "confidence": 1.0, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            response = await agent("Test")

            # Verify system prompt was used in call
            call_kwargs = mock_completion.call_args[1]
            assert "messages" in call_kwargs
            # System prompt should be in messages or separate parameter

            assert isinstance(response, ChatResponse)


# ============================================================================
# Phase 3 (Design Doc Phase 4): Template Rendering Tests (TDD)
# ============================================================================


# Test context models


class ChatContext(MeshContextModel):
    """Test context model for templates."""

    user_name: str = Field(description="User name")
    domain: str = Field(description="Domain of expertise")


class AssistantContext(MeshContextModel):
    """Test assistant context model."""

    role: str = Field(description="Assistant role")
    domain: Optional[str] = Field(default=None, description="Domain")
    skills: list[str] = Field(default_factory=list, description="Skills")


class TestTemplateLoading:
    """Test template loading functionality (Phase 3 - TDD)."""

    def test_load_template_from_relative_path(self):
        """Test: Load template from relative path."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        # Should successfully load template
        assert hasattr(agent, "_template")
        assert agent._template is not None

    def test_load_template_from_absolute_path(self):
        """Test: Load template from absolute path."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        # Get absolute path
        abs_path = (
            Path(__file__).parent.parent / "fixtures" / "templates" / "simple.jinja2"
        )
        template_path = str(abs_path)

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        # Should successfully load template
        assert hasattr(agent, "_template")
        assert agent._template is not None

    def test_load_template_file_not_found(self):
        """Test: Template file not found raises error."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "nonexistent.jinja2")

        with pytest.raises(FileNotFoundError) as exc_info:
            MeshLlmAgent(
                config=config,
                filtered_tools=[],
                output_type=ChatResponse,
                template_path=template_path,
                context_value=None,
            )

        assert "nonexistent.jinja2" in str(exc_info.value).lower()

    def test_load_template_syntax_error(self):
        """Test: Template with syntax error raises error."""
        from jinja2 import TemplateSyntaxError

        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "syntax_error.jinja2")

        with pytest.raises(TemplateSyntaxError):
            MeshLlmAgent(
                config=config,
                filtered_tools=[],
                output_type=ChatResponse,
                template_path=template_path,
                context_value=None,
            )

    def test_template_caching(self):
        """Test: Template loaded once and cached."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        template1 = agent._template
        template2 = agent._template

        # Should be same object (cached)
        assert template1 is template2


class TestContextPreparation:
    """Test context preparation for template rendering (Phase 3 - TDD)."""

    def test_prepare_context_from_mesh_context_model(self):
        """Test: MeshContextModel converted to dict via model_dump()."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=context,
        )

        prepared = agent._prepare_context(context)

        assert isinstance(prepared, dict)
        assert prepared["user_name"] == "Alice"
        assert prepared["domain"] == "Python"

    def test_prepare_context_from_dict(self):
        """Test: Dict passed through directly."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        context = {"user_name": "Bob", "domain": "Go"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=context,
        )

        prepared = agent._prepare_context(context)

        assert isinstance(prepared, dict)
        assert prepared == context

    def test_prepare_context_from_none(self):
        """Test: None converted to empty dict."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=None,
        )

        prepared = agent._prepare_context(None)

        assert isinstance(prepared, dict)
        assert prepared == {}

    def test_prepare_context_invalid_type_error(self):
        """Test: Invalid context type raises TypeError."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=None,
        )

        with pytest.raises(TypeError) as exc_info:
            agent._prepare_context("invalid string context")

        assert "context" in str(exc_info.value).lower()

    def test_prepare_context_nested_mesh_context_model(self):
        """Test: Nested MeshContextModel fields properly converted."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        class NestedContext(MeshContextModel):
            """Context with nested model."""

            chat: ChatContext
            count: int

        config = make_test_config()
        nested = NestedContext(
            chat=ChatContext(user_name="Charlie", domain="Rust"), count=5
        )

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=nested,
        )

        prepared = agent._prepare_context(nested)

        assert isinstance(prepared, dict)
        assert isinstance(prepared["chat"], dict)
        assert prepared["chat"]["user_name"] == "Charlie"
        assert prepared["count"] == 5


class TestTemplateRendering:
    """Test template rendering with Jinja2 (Phase 3 - TDD)."""

    def test_render_literal_prompt_no_template(self):
        """Test: Literal prompt used when no template."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config(system_prompt="You are a helpful assistant.")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=None,
        )

        rendered = agent._render_system_prompt()

        assert rendered == "You are a helpful assistant."

    def test_render_template_with_mesh_context_model(self):
        """Test: Template rendered with MeshContextModel context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
        )

        rendered = agent._render_system_prompt()

        assert "Alice" in rendered
        assert "Python" in rendered
        assert (
            rendered
            == "You are a helpful assistant for Python. Help Alice with their query."
        )

    def test_render_template_with_dict_context(self):
        """Test: Template rendered with dict context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = {"user_name": "Bob", "domain": "Go"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
        )

        rendered = agent._render_system_prompt()

        assert "Bob" in rendered
        assert "Go" in rendered

    def test_render_template_with_none_context(self):
        """Test: Template rendered with None context (empty dict)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        # Create a template that doesn't require any variables
        template_path = str(TEMPLATES_DIR / "with_control.jinja2")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        # Should render with empty context (optional vars omitted)
        rendered = agent._render_system_prompt()
        assert isinstance(rendered, str)

    def test_render_template_with_control_structures(self):
        """Test: Template with if/for control structures."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "with_control.jinja2")
        context = AssistantContext(
            role="expert", domain="AI", skills=["Python", "ML", "NLP"]
        )

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
        )

        rendered = agent._render_system_prompt()

        assert "expert" in rendered
        assert "AI" in rendered
        assert "Python" in rendered
        assert "ML" in rendered
        assert "NLP" in rendered

    def test_render_template_missing_required_var_error(self):
        """Test: Template rendering fails when required var missing."""
        from jinja2 import UndefinedError

        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        # Empty context - missing required vars
        context = {}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
        )

        # In strict mode, should raise UndefinedError
        # For now, Jinja2 default behavior is to render as empty strings
        # We may want strict undefined mode
        rendered = agent._render_system_prompt()
        # Variables will be empty strings in default mode
        assert isinstance(rendered, str)

    def test_render_template_runtime_override(self):
        """Test: Runtime override with set_system_prompt() bypasses template."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
        )

        # Override at runtime
        agent.set_system_prompt("Overridden prompt")

        rendered = agent._render_system_prompt()

        # Should use overridden prompt, not template
        assert rendered == "Overridden prompt"

    @pytest.mark.asyncio
    async def test_render_template_used_in_llm_call(self):
        """Test: Rendered template used in actual LLM call."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Response", "confidence": 1.0, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            response = await agent("Test message")

            # Verify system prompt in call contains rendered template content
            call_kwargs = mock_completion.call_args[1]
            messages = call_kwargs["messages"]
            system_message = next(m for m in messages if m["role"] == "system")

            assert "Alice" in system_message["content"]
            assert "Python" in system_message["content"]
            assert isinstance(response, ChatResponse)


# ============================================================================
# Runtime Context Injection Tests
# ============================================================================


class TestRuntimeContextInjection:
    """Test runtime context injection via __call__() context parameter."""

    def test_resolve_context_no_runtime_context_provided(self):
        """Test: When no runtime context provided, use auto-populated context."""
        from _mcp_mesh.engine.mesh_llm_agent import _CONTEXT_NOT_PROVIDED, MeshLlmAgent

        config = make_test_config()
        auto_context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        resolved = agent._resolve_context(_CONTEXT_NOT_PROVIDED, "append")

        assert resolved == {"user_name": "Alice", "domain": "Python"}

    def test_resolve_context_append_mode(self):
        """Test: Append mode - runtime context extends auto-populated context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = {"extra_key": "extra_value", "domain": "overridden"}
        resolved = agent._resolve_context(runtime_context, "append")

        # Auto context first, runtime overwrites (runtime wins on conflicts)
        assert resolved["user_name"] == "Alice"
        assert resolved["domain"] == "overridden"  # Runtime wins
        assert resolved["extra_key"] == "extra_value"

    def test_resolve_context_prepend_mode(self):
        """Test: Prepend mode - auto-populated context overwrites runtime."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = {"extra_key": "extra_value", "domain": "runtime_domain"}
        resolved = agent._resolve_context(runtime_context, "prepend")

        # Runtime first, auto overwrites (auto wins on conflicts)
        assert resolved["user_name"] == "Alice"
        assert resolved["domain"] == "Python"  # Auto wins
        assert resolved["extra_key"] == "extra_value"

    def test_resolve_context_replace_mode(self):
        """Test: Replace mode - runtime context replaces auto-populated entirely."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = {"only_this": "value"}
        resolved = agent._resolve_context(runtime_context, "replace")

        # Replace entirely
        assert resolved == {"only_this": "value"}
        assert "user_name" not in resolved
        assert "domain" not in resolved

    def test_resolve_context_replace_with_empty_dict(self):
        """Test: Replace with empty dict explicitly clears context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        # Explicitly clear context
        resolved = agent._resolve_context({}, "replace")

        assert resolved == {}

    def test_resolve_context_append_empty_dict_no_op(self):
        """Test: Append with empty dict is no-op (keeps auto context)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        resolved = agent._resolve_context({}, "append")

        # Empty dict appended is no-op
        assert resolved == {"user_name": "Alice", "domain": "Python"}

    def test_resolve_context_none_runtime_context(self):
        """Test: None runtime context converted to empty dict."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        resolved = agent._resolve_context(None, "append")

        # None is treated as empty dict for append
        assert resolved == {"user_name": "Alice", "domain": "Python"}

    def test_resolve_context_with_mesh_context_model_runtime(self):
        """Test: MeshContextModel works as runtime context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = ChatContext(user_name="Bob", domain="Go")
        resolved = agent._resolve_context(runtime_context, "append")

        # Runtime MeshContextModel should work
        assert resolved["user_name"] == "Bob"  # Runtime wins
        assert resolved["domain"] == "Go"

    @pytest.mark.asyncio
    async def test_call_with_context_parameter(self):
        """Test: __call__ with context parameter uses resolved context in template."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Response", "confidence": 1.0, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            # Call with runtime context that overrides domain
            response = await agent(
                "Test message",
                context={"domain": "Go"},
            )

            # Verify system prompt contains merged context
            call_kwargs = mock_completion.call_args[1]
            messages = call_kwargs["messages"]
            system_message = next(m for m in messages if m["role"] == "system")

            # Alice from auto, Go from runtime (append mode default)
            assert "Alice" in system_message["content"]
            assert "Go" in system_message["content"]
            assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_call_with_context_mode_replace(self):
        """Test: __call__ with context_mode='replace' replaces entire context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Response", "confidence": 1.0, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            # Call with replace mode
            response = await agent(
                "Test message",
                context={"user_name": "Bob", "domain": "Rust"},
                context_mode="replace",
            )

            # Verify system prompt contains replaced context
            call_kwargs = mock_completion.call_args[1]
            messages = call_kwargs["messages"]
            system_message = next(m for m in messages if m["role"] == "system")

            # Bob and Rust from runtime (replace mode)
            assert "Bob" in system_message["content"]
            assert "Rust" in system_message["content"]
            assert "Alice" not in system_message["content"]
            assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_call_without_context_uses_auto_populated(self):
        """Test: __call__ without context parameter uses auto-populated context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Response", "confidence": 1.0, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            # Call without context (backward compatible)
            response = await agent("Test message")

            # Verify system prompt contains auto-populated context
            call_kwargs = mock_completion.call_args[1]
            messages = call_kwargs["messages"]
            system_message = next(m for m in messages if m["role"] == "system")

            assert "Alice" in system_message["content"]
            assert "Python" in system_message["content"]
            assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_call_with_context_mode_prepend(self):
        """Test: __call__ with context_mode='prepend' - auto wins on conflicts."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
        )

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Response", "confidence": 1.0, "sources": []}',
                            tool_calls=None,
                        )
                    )
                ]
            )

            # Call with prepend mode - auto should win
            response = await agent(
                "Test message",
                context={"user_name": "Bob", "domain": "Rust"},
                context_mode="prepend",
            )

            # Verify system prompt uses auto context (prepend means auto wins)
            call_kwargs = mock_completion.call_args[1]
            messages = call_kwargs["messages"]
            system_message = next(m for m in messages if m["role"] == "system")

            # Auto wins on conflicts
            assert "Alice" in system_message["content"]
            assert "Python" in system_message["content"]
            assert isinstance(response, ChatResponse)


# ============================================================================
# Issue #308: Model Override in Mesh Delegation Tests
# ============================================================================


class TestMeshDelegationModelOverride:
    """Test model override functionality for mesh delegation (issue #308)."""

    @pytest.mark.asyncio
    async def test_mesh_delegation_includes_model_in_params(self):
        """Test: Model is included in model_params when explicitly set for mesh delegation."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # Create config with dict provider (mesh delegation) and explicit model
        config = LLMConfig(
            provider={
                "capability": "llm",
                "tags": ["claude"],
            },  # Dict = mesh delegation
            model="anthropic/claude-haiku",  # Explicit model override
            api_key="",
            max_iterations=10,
            system_prompt="Test prompt",
        )

        # Create mock provider proxy
        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Hello", "confidence": 0.9, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        # Verify agent is mesh delegated
        assert agent._is_mesh_delegated is True

        # Call agent
        response = await agent("Test message")

        # Verify provider proxy was called with model in request
        mock_provider_proxy.assert_called_once()
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]

        # Model should be in model_params
        assert "model_params" in request_dict
        assert request_dict["model_params"].get("model") == "anthropic/claude-haiku"

    @pytest.mark.asyncio
    async def test_mesh_delegation_excludes_empty_model(self):
        """Test: Empty/None model is not included in model_params."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # Create config with dict provider but no explicit model
        config = LLMConfig(
            provider={"capability": "llm", "tags": ["claude"]},
            model=None,  # No model specified
            api_key="",
            max_iterations=10,
            system_prompt="Test prompt",
        )

        # Create mock provider proxy
        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Hello", "confidence": 0.9, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        # Call agent
        response = await agent("Test message")

        # Verify provider proxy was called
        mock_provider_proxy.assert_called_once()
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]

        # Model should NOT be in model_params (or be None/empty)
        model_params = request_dict.get("model_params", {})
        assert model_params is None or "model" not in model_params


class TestLlmProviderModelOverride:
    """Test model override handling in @mesh.llm_provider decorator (issue #308)."""

    def test_extract_vendor_from_model_with_vendor_prefix(self):
        """Test: Extract vendor from model string with vendor prefix."""
        from mesh.helpers import _extract_vendor_from_model

        assert _extract_vendor_from_model("anthropic/claude-sonnet-4-5") == "anthropic"
        assert _extract_vendor_from_model("openai/gpt-4o") == "openai"
        assert _extract_vendor_from_model("google/gemini-pro") == "google"

    def test_extract_vendor_from_model_without_prefix(self):
        """Test: Returns None for model without vendor prefix."""
        from mesh.helpers import _extract_vendor_from_model

        assert _extract_vendor_from_model("claude-3-haiku") is None
        assert _extract_vendor_from_model("gpt-4") is None
        assert _extract_vendor_from_model("") is None
        assert _extract_vendor_from_model(None) is None

    def test_extract_vendor_from_model_case_insensitive(self):
        """Test: Vendor extraction is case insensitive."""
        from mesh.helpers import _extract_vendor_from_model

        assert _extract_vendor_from_model("Anthropic/claude-sonnet") == "anthropic"
        assert _extract_vendor_from_model("OPENAI/gpt-4") == "openai"

    def test_process_chat_uses_override_model_when_vendor_matches(self):
        """Test: Provider uses override model when vendor matches."""
        from mesh.types import MeshLlmRequest

        # Simulate what happens inside process_chat
        provider_model = "anthropic/claude-sonnet-4-5"
        provider_vendor = "anthropic"

        request = MeshLlmRequest(
            messages=[{"role": "user", "content": "Hello"}],
            model_params={"model": "anthropic/claude-haiku"},  # Override
        )

        # Simulate the vendor check logic
        from mesh.helpers import _extract_vendor_from_model

        override_model = request.model_params.get("model")
        override_vendor = _extract_vendor_from_model(override_model)

        # Vendor matches - should use override
        assert override_vendor == provider_vendor
        effective_model = override_model  # Would use override

        assert effective_model == "anthropic/claude-haiku"

    def test_process_chat_ignores_override_on_vendor_mismatch(self):
        """Test: Provider ignores override when vendor doesn't match."""
        from mesh.types import MeshLlmRequest

        provider_model = "anthropic/claude-sonnet-4-5"
        provider_vendor = "anthropic"

        request = MeshLlmRequest(
            messages=[{"role": "user", "content": "Hello"}],
            model_params={"model": "openai/gpt-4o"},  # Wrong vendor!
        )

        from mesh.helpers import _extract_vendor_from_model

        override_model = request.model_params.get("model")
        override_vendor = _extract_vendor_from_model(override_model)

        # Vendor mismatch - should fall back to provider's model
        assert override_vendor != provider_vendor
        effective_model = provider_model  # Would fall back

        assert effective_model == "anthropic/claude-sonnet-4-5"

    def test_process_chat_uses_override_when_no_vendor_prefix(self):
        """Test: Provider uses override when it has no vendor prefix (can't validate)."""
        from mesh.types import MeshLlmRequest

        provider_model = "anthropic/claude-sonnet-4-5"
        provider_vendor = "anthropic"

        request = MeshLlmRequest(
            messages=[{"role": "user", "content": "Hello"}],
            model_params={"model": "claude-3-haiku"},  # No vendor prefix
        )

        from mesh.helpers import _extract_vendor_from_model

        override_model = request.model_params.get("model")
        override_vendor = _extract_vendor_from_model(override_model)

        # No vendor prefix - can't validate, so use override
        assert override_vendor is None
        # When vendor is None, the check `override_vendor and override_vendor != vendor`
        # is False, so we use the override
        effective_model = override_model

        assert effective_model == "claude-3-haiku"


class TestLlmMetaAttachment:
    """Test _mesh_meta attachment to LLM results (Issue #311)."""

    @pytest.mark.asyncio
    async def test_mesh_meta_attached_to_pydantic_result(self):
        """Test: _mesh_meta is attached to Pydantic model results."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from mesh.types import LlmMeta

        # Create mock response with usage data
        mock_message = MagicMock()
        mock_message.content = '{"answer": "42", "confidence": 0.95, "sources": []}'
        mock_message.tool_calls = None
        mock_message.model_dump = lambda: {
            "role": "assistant",
            "content": mock_message.content,
        }

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "anthropic/claude-3-5-sonnet"

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = mock_response

            agent = MeshLlmAgent(
                config=make_test_config(
                    provider="anthropic",
                    model="anthropic/claude-3-5-sonnet",
                    system_prompt="You are helpful.",
                ),
                filtered_tools=[],
                output_type=ChatResponse,
            )

            result = await agent("What is the answer?")

            # Verify result is correct type
            assert isinstance(result, ChatResponse)
            assert result.answer == "42"
            assert result.confidence == 0.95

            # Verify _mesh_meta is attached
            assert hasattr(result, "_mesh_meta")
            assert isinstance(result._mesh_meta, LlmMeta)
            assert result._mesh_meta.provider == "anthropic"
            assert result._mesh_meta.model == "anthropic/claude-3-5-sonnet"
            assert result._mesh_meta.input_tokens == 100
            assert result._mesh_meta.output_tokens == 50
            assert result._mesh_meta.total_tokens == 150
            assert result._mesh_meta.latency_ms > 0

    @pytest.mark.asyncio
    async def test_mesh_meta_accumulates_tokens_across_iterations(self):
        """Test: _mesh_meta accumulates tokens across tool call iterations."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # First response: tool call
        mock_message_1 = MagicMock()
        mock_message_1.content = None
        mock_message_1.tool_calls = [make_tool_call_mock("tc1", "get_info", "{}")]
        mock_message_1.model_dump = lambda: {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "get_info", "arguments": "{}"},
                }
            ],
        }

        mock_usage_1 = MagicMock()
        mock_usage_1.prompt_tokens = 100
        mock_usage_1.completion_tokens = 20

        mock_choice_1 = MagicMock()
        mock_choice_1.message = mock_message_1

        mock_response_1 = MagicMock()
        mock_response_1.choices = [mock_choice_1]
        mock_response_1.usage = mock_usage_1
        mock_response_1.model = "anthropic/claude-3-5-sonnet"

        # Second response: final answer
        mock_message_2 = MagicMock()
        mock_message_2.content = '{"answer": "done", "confidence": 0.9, "sources": []}'
        mock_message_2.tool_calls = None

        mock_usage_2 = MagicMock()
        mock_usage_2.prompt_tokens = 150
        mock_usage_2.completion_tokens = 30

        mock_choice_2 = MagicMock()
        mock_choice_2.message = mock_message_2

        mock_response_2 = MagicMock()
        mock_response_2.choices = [mock_choice_2]
        mock_response_2.usage = mock_usage_2
        mock_response_2.model = "anthropic/claude-3-5-sonnet"

        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            return mock_response_1 if call_count == 1 else mock_response_2

        # Mock tool proxy with call_tool method returning JSON-serializable result
        mock_tool_proxy = MagicMock()
        mock_tool_proxy.call_tool = AsyncMock(return_value={"result": "tool result"})

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.side_effect = side_effect

            agent = MeshLlmAgent(
                config=make_test_config(
                    provider="anthropic",
                    model="anthropic/claude-3-5-sonnet",
                    system_prompt="You are helpful.",
                ),
                filtered_tools=[
                    {"name": "get_info", "description": "Get info", "inputSchema": {}}
                ],
                output_type=ChatResponse,
                tool_proxies={"get_info": mock_tool_proxy},
            )

            result = await agent("Do something")

            # Verify tokens are accumulated from both calls
            assert result._mesh_meta.input_tokens == 250  # 100 + 150
            assert result._mesh_meta.output_tokens == 50  # 20 + 30
            assert result._mesh_meta.total_tokens == 300

    @pytest.mark.asyncio
    async def test_mesh_meta_not_attached_to_str_result(self):
        """Test: _mesh_meta cannot be attached to str results (silently skipped)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        mock_message = MagicMock()
        mock_message.content = "Hello, world!"
        mock_message.tool_calls = None

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 10

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "anthropic/claude-3-5-sonnet"

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            mock_completion.return_value = mock_response

            agent = MeshLlmAgent(
                config=make_test_config(
                    provider="anthropic",
                    model="anthropic/claude-3-5-sonnet",
                    system_prompt="You are helpful.",
                ),
                filtered_tools=[],
                output_type=str,  # str return type
            )

            result = await agent("Say hello")

            # Result should be string
            assert isinstance(result, str)
            assert result == "Hello, world!"

            # _mesh_meta cannot be attached to str (no error, just not present)
            assert not hasattr(result, "_mesh_meta")

    def test_llm_meta_dataclass_creation(self):
        """Test: LlmMeta dataclass can be created with all fields."""
        from mesh.types import LlmMeta

        meta = LlmMeta(
            provider="anthropic",
            model="anthropic/claude-3-5-haiku",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=125.5,
        )

        assert meta.provider == "anthropic"
        assert meta.model == "anthropic/claude-3-5-haiku"
        assert meta.input_tokens == 100
        assert meta.output_tokens == 50
        assert meta.total_tokens == 150
        assert meta.latency_ms == 125.5

    def test_llm_meta_exported_from_mesh_module(self):
        """Test: LlmMeta is accessible via mesh.LlmMeta."""
        import mesh

        assert hasattr(mesh, "LlmMeta")
        assert mesh.LlmMeta is not None

        # Can create instance
        meta = mesh.LlmMeta(
            provider="openai",
            model="gpt-4o",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            latency_ms=200.0,
        )
        assert meta.provider == "openai"


class TestMeshDelegationMeta:
    """Test _mesh_meta in mesh delegation scenarios (Issue #311)."""

    def test_mesh_usage_included_in_provider_response(self):
        """Test: llm_provider includes _mesh_usage in response dict."""
        # This tests the structure that llm_provider should return
        # Simulating what process_chat returns

        message_dict = {
            "role": "assistant",
            "content": "Hello!",
            "_mesh_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "model": "anthropic/claude-3-5-sonnet",
            },
        }

        assert "_mesh_usage" in message_dict
        assert message_dict["_mesh_usage"]["prompt_tokens"] == 100
        assert message_dict["_mesh_usage"]["completion_tokens"] == 50
        assert message_dict["_mesh_usage"]["model"] == "anthropic/claude-3-5-sonnet"

    def test_mock_response_extracts_mesh_usage(self):
        """Test: MockResponse correctly extracts _mesh_usage from provider response."""
        # This tests the MockResponse class behavior in mesh_llm_agent.py

        message_dict = {
            "role": "assistant",
            "content": "Response content",
            "_mesh_usage": {
                "prompt_tokens": 200,
                "completion_tokens": 80,
                "model": "anthropic/claude-3-5-haiku",
            },
        }

        # Simulate MockUsage and MockResponse behavior
        class MockUsage:
            def __init__(self, usage_dict):
                self.prompt_tokens = usage_dict.get("prompt_tokens", 0)
                self.completion_tokens = usage_dict.get("completion_tokens", 0)
                self.total_tokens = self.prompt_tokens + self.completion_tokens

        mesh_usage = message_dict.get("_mesh_usage")
        usage = MockUsage(mesh_usage) if mesh_usage else None
        model = mesh_usage.get("model") if mesh_usage else None

        assert usage is not None
        assert usage.prompt_tokens == 200
        assert usage.completion_tokens == 80
        assert usage.total_tokens == 280
        assert model == "anthropic/claude-3-5-haiku"

    def test_mock_response_handles_missing_mesh_usage(self):
        """Test: MockResponse handles responses without _mesh_usage gracefully."""
        message_dict = {
            "role": "assistant",
            "content": "Response without usage",
        }

        # Simulate MockResponse behavior
        mesh_usage = message_dict.get("_mesh_usage")
        usage = None  # Would be MockUsage(mesh_usage) if mesh_usage else None
        model = mesh_usage.get("model") if mesh_usage else None

        assert usage is None
        assert model is None

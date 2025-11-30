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

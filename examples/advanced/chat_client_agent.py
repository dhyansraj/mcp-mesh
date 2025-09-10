#!/usr/bin/env python3
"""
MCP Mesh Chat Client Agent

This agent demonstrates dependency injection to call the LLM Chat Agent.
It acts as a conversational interface that delegates LLM processing to the
llm-chat-agent via MCP Mesh dependency injection.

Usage:
1. Start the llm-chat-agent first
2. Start this chat client agent
3. Call the chat tools to interact with the LLM through mesh
"""

import os
from typing import Any, Dict, Optional

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Chat Client Service")


@app.tool()
@mesh.tool(
    capability="chat_interface",
    dependencies=[
        "llm-service"
    ],  # Depends on LLM service capability from llm-chat-agent
    description="Simple chat interface that delegates to LLM agent",
)
async def simple_chat(
    message: str,
    task: str = "analyze",
    context: Optional[str] = None,
    model: str = "claude-3-5-sonnet-20241022",
    llm_service: mesh.McpMeshAgent | None = None,
) -> Dict[str, str]:
    """
    Simple chat interface using dependency injection to call LLM agent.

    Args:
        message: The message/text to process
        task: Processing task (analyze, summarize, interpret, classify, extract)
        context: Optional context for the processing
        model: Claude model to use (defaults to claude-3-5-sonnet-20241022)
        llm_service: Injected LLM service from llm-chat-agent

    Returns:
        Chat response with LLM processing results
    """
    if llm_service is None:
        return {
            "error": "LLM service not available",
            "message": message,
            "status": "service_unavailable",
        }

    try:
        # Call the injected LLM service using natural async pattern
        # This will call process_text_with_llm on the llm-chat-agent
        llm_response = llm_service(
            text=message,
            task=task,
            context=context or "User chat interaction",
            model=model,
            max_tokens=8000,  # Increased for complex analysis
            temperature=0.7,
        )

        return {
            "user_message": message,
            "llm_response": str(llm_response),
            "task": task,
            "status": "success",
        }
    except Exception as e:
        return {
            "error": f"Failed to process with LLM: {e}",
            "message": message,
            "status": "processing_error",
        }


@app.tool()
@mesh.tool(
    capability="chat_health_check",
    dependencies=["llm-service"],  # Simple dependency to check LLM service
    description="Check if LLM chat services are available and working",
)
async def health_check(llm_service: mesh.McpMeshAgent | None = None) -> Dict[str, str]:
    """
    Health check for the chat client and its dependencies.

    Args:
        llm_service: Injected LLM service

    Returns:
        Health status of chat services
    """
    status = {
        "chat_client": "healthy",
        "llm_service": "unavailable",
        "timestamp": "unknown",
    }

    if llm_service is not None:
        try:
            # Try a simple test call without tools for health check
            test_result = llm_service(
                text="Health check test",
                task="analyze",
                context="System health check",
                model="claude-3-5-sonnet-20241022",
                max_tokens=50,
                temperature=0.1,
            )

            status["llm_service"] = "healthy"
            if isinstance(test_result, dict):
                status["timestamp"] = str(test_result.get("timestamp", "unknown"))
            status["test_successful"] = "true"

        except Exception as e:
            status["llm_service"] = f"error: {e}"
            status["test_successful"] = "false"

    return status


@app.tool()
@mesh.tool(
    capability="file_analysis",
    dependencies=["llm-service"],  # Depends on LLM service for file content analysis
    description="Read file from disk and analyze content using LLM agent",
)
async def analyze_file(
    file_path: str,
    task: str = "analyze",
    context: Optional[str] = None,
    model: str = "claude-3-5-sonnet-20241022",
    llm_service: mesh.McpMeshAgent | None = None,
) -> Dict[str, Any]:
    """
    Read a file from disk and analyze its content using the LLM agent.

    Args:
        file_path: Path to the file to read and analyze
        task: Analysis task (analyze, summarize, interpret, classify, extract)
        context: Optional context for the analysis
        model: Claude model to use (defaults to claude-3-5-sonnet-20241022)
        llm_service: Injected LLM service from llm-chat-agent

    Returns:
        File analysis results from LLM agent
    """
    if llm_service is None:
        return {
            "error": "LLM service not available",
            "file_path": file_path,
            "status": "service_unavailable",
        }

    # Check if file exists
    if not os.path.exists(file_path):
        return {
            "error": f"File not found: {file_path}",
            "file_path": file_path,
            "status": "file_not_found",
        }

    # Check if it's a file (not directory)
    if not os.path.isfile(file_path):
        return {
            "error": f"Path is not a file: {file_path}",
            "file_path": file_path,
            "status": "not_a_file",
        }

    try:
        # Read complete file content (no truncation)
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()

        # Get file size for metadata
        file_size = os.path.getsize(file_path)

        # Prepare context for LLM
        analysis_context = f"File analysis of: {os.path.basename(file_path)}"
        if context:
            analysis_context += f" | {context}"

        # Define complex tool schema for structured analysis
        analysis_tool = {
            "name": "analyze_document_structured",
            "description": "Extract structured information from document content",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_type": {
                        "type": "string",
                        "enum": [
                            "resume",
                            "cover_letter",
                            "technical_document",
                            "report",
                            "other",
                        ],
                        "description": "Type of document identified",
                    },
                    "professional_summary": {
                        "type": "string",
                        "description": "Brief professional summary if applicable",
                    },
                    "technical_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of technical skills and technologies mentioned",
                    },
                    "key_insights": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key insights and important findings from the document",
                    },
                    "experience_years": {
                        "type": "number",
                        "description": "Number of years of experience mentioned, if applicable",
                    },
                    "education_info": {
                        "type": "object",
                        "properties": {
                            "highest_degree": {"type": "string"},
                            "institution": {"type": "string"},
                            "field_of_study": {"type": "string"},
                        },
                    },
                    "work_experience": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "company": {"type": "string"},
                                "duration": {"type": "string"},
                                "key_achievements": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                    "quality_assessment": {
                        "type": "object",
                        "properties": {
                            "overall_score": {
                                "type": "number",
                                "minimum": 1,
                                "maximum": 10,
                                "description": "Overall document quality score",
                            },
                            "strengths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Document strengths identified",
                            },
                            "areas_for_improvement": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Areas that could be improved",
                            },
                        },
                        "required": ["overall_score"],
                    },
                    "content_summary": {
                        "type": "string",
                        "description": "Comprehensive summary of document content",
                    },
                },
                "required": ["document_type", "content_summary", "key_insights"],
            },
        }

        # Call LLM service for analysis with structured tool using natural async pattern
        llm_response = llm_service(
            text=content,
            task=task,
            context=analysis_context,
            model=model,
            max_tokens=8000,  # Increased for large PDF analysis
            temperature=0.3,  # Lower for more consistent structured output
            tools=[analysis_tool],
            force_tool_use=True,
        )

        # Process structured response - now unified proxy returns clean Python dicts
        structured_analysis = None

        # Handle unified Python dict responses from proxy
        if isinstance(llm_response, dict):
            if llm_response.get("success") and llm_response.get("tool_calls"):
                # Direct dict format from unified proxy conversion
                structured_analysis = llm_response["tool_calls"][0]["parameters"]
            elif "structuredContent" in llm_response:
                # Nested format (legacy compatibility)
                structured_content = llm_response["structuredContent"]
                if structured_content.get("success") and structured_content.get(
                    "tool_calls"
                ):
                    structured_analysis = structured_content["tool_calls"][0][
                        "parameters"
                    ]

        return {
            "file_path": file_path,
            "file_size": str(file_size),
            "content_length": str(len(content)),
            "task": task,
            "llm_raw_response": str(llm_response),
            "structured_analysis": structured_analysis,
            "analysis_enhanced": structured_analysis is not None,
            "model_used": (
                llm_response.get("model", "unknown")
                if isinstance(llm_response, dict)
                else "unknown"
            ),
            "token_usage": (
                llm_response.get("usage", {}) if isinstance(llm_response, dict) else {}
            ),
            "status": "success",
        }

    except UnicodeDecodeError:
        return {
            "error": f"Cannot read file as UTF-8 text: {file_path}",
            "file_path": file_path,
            "status": "encoding_error",
        }
    except PermissionError:
        return {
            "error": f"Permission denied reading file: {file_path}",
            "file_path": file_path,
            "status": "permission_denied",
        }
    except Exception as e:
        return {
            "error": f"Failed to analyze file: {e}",
            "file_path": file_path,
            "status": "analysis_error",
        }


# AGENT configuration
@mesh.agent(
    name="chat-client",
    version="1.0.0",
    description="Chat client that uses dependency injection to call LLM chat agent",
    http_port=9094,  # Different port from LLM agent
    enable_http=True,
    auto_run=True,
)
class ChatClientAgent:
    """
    Chat Client Agent that demonstrates dependency injection patterns.

    This agent acts as a conversational interface that delegates all LLM
    processing to the llm-chat-agent via MCP Mesh dependency injection.

    Key features:
    - Dependency injection for LLM services using mesh.McpMeshAgent typing
    - Conversational interface
    - Health checking
    - Error handling and graceful degradation
    """

    pass


# The mesh processor will automatically:
# 1. Discover the 'app' FastMCP instance
# 2. Apply dependency injection based on capability names
# 3. Start the HTTP server on port 9094
# 4. Register capabilities with the mesh registry
# 5. Connect to llm-chat-agent when available

#!/usr/bin/env python3
"""
Chat Test Agent

Demonstrates interaction with the chat agent using:
- Regular chat completion
- Streaming chat responses
- Session management
- Software knowledge queries
"""

from datetime import datetime

import mesh
from fastmcp import FastMCP
from mesh.types import McpAgent

# Single FastMCP server instance
app = FastMCP("Chat Test Service")


@app.tool()
@mesh.tool(capability="test_chat_basic", dependencies=["chat_completion"])
async def test_basic_chat(
    question: str = "What are Python best practices?", chat_completion: McpAgent = None
) -> dict:
    """Test basic chat functionality with the AI assistant."""
    if not chat_completion:
        return {"error": "No chat_completion service available"}

    try:
        # Start new conversation
        conversation_result = await chat_completion(
            capability="new_conversation", topic="Python best practices"
        )

        if "structuredContent" in conversation_result:
            conversation_id = conversation_result["structuredContent"][
                "conversation_id"
            ]
        else:
            conversation_id = f"test-chat-{datetime.now().strftime('%H%M%S')}"

        # Ask question
        chat_result = await chat_completion(
            message=question,
            conversation_id=conversation_id,
            model="gpt-4",
            temperature=0.7,
        )

        return {
            "question": question,
            "conversation_id": conversation_id,
            "response": chat_result,
            "test_status": "completed",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Chat test failed: {str(e)}",
            "question": question,
            "timestamp": datetime.now().isoformat(),
        }


@app.tool()
@mesh.tool(capability="test_streaming_chat", dependencies=["streaming_chat"])
async def test_streaming_chat(
    question: str = "Explain microservices architecture and its benefits",
    streaming_chat: McpAgent = None,
) -> dict:
    """Test streaming chat functionality."""
    if not streaming_chat:
        return {"error": "No streaming_chat service available"}

    try:
        conversation_id = f"stream-test-{datetime.now().strftime('%H%M%S')}"

        # Test streaming response
        stream_chunks = []
        full_response = ""

        # Use call_tool_streaming for streaming responses
        async for chunk in streaming_chat.call_tool_streaming(
            "stream_chat_response",
            {
                "message": question,
                "conversation_id": conversation_id,
                "model": "gpt-4",
                "temperature": 0.7,
            },
        ):
            stream_chunks.append(chunk)
            if "content" in chunk:
                full_response += chunk["content"]

        return {
            "question": question,
            "conversation_id": conversation_id,
            "stream_chunks_count": len(stream_chunks),
            "full_response": full_response,
            "first_chunk": stream_chunks[0] if stream_chunks else None,
            "last_chunk": stream_chunks[-1] if stream_chunks else None,
            "test_status": "completed",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Streaming chat test failed: {str(e)}",
            "question": question,
            "timestamp": datetime.now().isoformat(),
        }


@app.tool()
@mesh.tool(
    capability="test_software_knowledge", dependencies=["software_knowledge_search"]
)
async def test_knowledge_search(
    query: str = "async programming",
    category: str = "programming",
    software_knowledge_search: mesh.McpMeshAgent = None,
) -> dict:
    """Test software knowledge search functionality."""
    if not software_knowledge_search:
        return {"error": "No software_knowledge_search service available"}

    try:
        # Search knowledge base
        search_result = software_knowledge_search(
            query=query, category=category, max_results=3
        )

        return {
            "query": query,
            "category": category,
            "search_result": search_result,
            "test_status": "completed",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Knowledge search test failed: {str(e)}",
            "query": query,
            "timestamp": datetime.now().isoformat(),
        }


@app.tool()
@mesh.tool(
    capability="test_conversation_management",
    dependencies=["new_conversation", "conversation_history", "clear_conversation"],
)
async def test_conversation_features(
    new_conversation: mesh.McpMeshAgent = None,
    conversation_history: mesh.McpMeshAgent = None,
    clear_conversation: mesh.McpMeshAgent = None,
) -> dict:
    """Test conversation management features."""
    if not all([new_conversation, conversation_history, clear_conversation]):
        return {"error": "Missing conversation management services"}

    try:
        # Start new conversation
        new_conv_result = new_conversation(topic="Testing conversation features")
        conversation_id = new_conv_result.get(
            "conversation_id", f"test-{datetime.now().strftime('%H%M%S')}"
        )

        # Get initial history (should be empty)
        initial_history = conversation_history(conversation_id=conversation_id)

        # Clear conversation
        clear_result = clear_conversation(conversation_id=conversation_id)

        # Get history after clear
        final_history = conversation_history(conversation_id=conversation_id)

        return {
            "conversation_id": conversation_id,
            "new_conversation": new_conv_result,
            "initial_history": initial_history,
            "clear_result": clear_result,
            "final_history": final_history,
            "test_status": "completed",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Conversation management test failed: {str(e)}",
            "timestamp": datetime.now().isoformat(),
        }


@app.tool()
@mesh.tool(
    capability="test_prompt_decoration",
    dependencies=["enhanced_chat_with_prompts", "code_review_prompt"],
)
async def test_prompt_decoration(
    enhanced_chat_with_prompts: McpAgent = None,
    code_review_prompt: mesh.McpMeshAgent = None,
) -> dict:
    """Test MCP prompt decoration features."""
    if not all([enhanced_chat_with_prompts, code_review_prompt]):
        return {"error": "Missing prompt decoration services"}

    try:
        conversation_id = f"prompt-test-{datetime.now().strftime('%H%M%S')}"

        # Test 1: Code review prompt
        sample_code = """
def calculate_total(items):
    total = 0
    for item in items:
        total += item['price'] * item['quantity']
    return total
"""

        code_review_result = await enhanced_chat_with_prompts(
            user_input="Please review this code",
            conversation_id=conversation_id,
            prompt_type="code_review",
            context_data=sample_code,
        )

        # Test 2: Architecture prompt
        architecture_result = await enhanced_chat_with_prompts(
            user_input="Design a system",
            conversation_id=conversation_id,
            prompt_type="architecture",
            context_data="E-commerce platform with user accounts, product catalog, shopping cart, and payment processing",
        )

        # Test 3: Debugging prompt
        debugging_result = await enhanced_chat_with_prompts(
            user_input="Help debug this error",
            conversation_id=conversation_id,
            prompt_type="debugging",
            context_data="ConnectionError: Failed to connect to database at localhost:5432",
        )

        # Test 4: Get raw prompt template
        raw_prompt = code_review_prompt(
            code=sample_code, language="python", focus_areas="security,performance"
        )

        return {
            "conversation_id": conversation_id,
            "tests": {
                "code_review": code_review_result,
                "architecture": architecture_result,
                "debugging": debugging_result,
                "raw_prompt_template": {
                    "prompt": (
                        raw_prompt[:500] + "..."
                        if len(raw_prompt) > 500
                        else raw_prompt
                    ),
                    "full_length": len(raw_prompt),
                },
            },
            "test_status": "completed",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Prompt decoration test failed: {str(e)}",
            "timestamp": datetime.now().isoformat(),
        }


@app.tool()
@mesh.tool(
    capability="comprehensive_chat_test",
    dependencies=["chat_completion", "streaming_chat", "software_knowledge_search"],
)
async def run_comprehensive_chat_test(
    chat_completion: McpAgent = None,
    streaming_chat: McpAgent = None,
    software_knowledge_search: mesh.McpMeshAgent = None,
) -> dict:
    """Run comprehensive test of all chat agent features."""
    if not all([chat_completion, streaming_chat, software_knowledge_search]):
        return {"error": "Missing required chat services"}

    test_results = {}

    try:
        # Test 1: Basic chat
        test_results["basic_chat"] = await test_basic_chat(
            "What are the key principles of clean code?", chat_completion
        )

        # Test 2: Streaming chat
        test_results["streaming_chat"] = await test_streaming_chat(
            "Explain the differences between REST and GraphQL APIs", streaming_chat
        )

        # Test 3: Knowledge search
        test_results["knowledge_search"] = await test_knowledge_search(
            "microservices", "architecture", software_knowledge_search
        )

        # Test 4: Different categories
        test_results["devops_knowledge"] = await test_knowledge_search(
            "ci/cd", "devops", software_knowledge_search
        )

        return {
            "test_suite": "comprehensive_chat_test",
            "total_tests": 4,
            "results": test_results,
            "overall_status": "completed",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Comprehensive test failed: {str(e)}",
            "partial_results": test_results,
            "timestamp": datetime.now().isoformat(),
        }


# AGENT configuration
@mesh.agent(
    name="chat-test-service",
    version="1.0.0",
    description="Test service for chat agent functionality",
    http_port=9095,
    enable_http=True,
    auto_run=True,
)
class ChatTestService:
    """
    Test agent for validating chat agent functionality.

    Tests:
    - Basic chat completion
    - Streaming responses
    - Knowledge base search
    - Conversation management
    - MCP protocol compliance
    """

    pass

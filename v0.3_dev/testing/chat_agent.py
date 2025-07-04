#!/usr/bin/env python3
"""
Chat Agent with OpenAI Integration

A streaming chat agent that provides software engineering assistance using:
- OpenAI GPT models for intelligent responses
- MCP protocol with streaming support
- Session management for conversation context
- Software field specialization
"""

import os
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Software Chat Assistant")


@app.tool()
@mesh.tool(
    capability="chat_completion",
    tags=["chat", "ai", "software", "streaming"],
    session_required=True,
    stateful=True,
)
async def chat_with_assistant(
    message: str,
    conversation_id: str,
    model: str = "gpt-4",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    system_prompt: Optional[str] = None,
) -> Dict:
    """
    Chat with AI assistant specialized in software engineering topics.

    Maintains conversation context and provides intelligent responses
    for programming, architecture, debugging, and technical questions.
    """
    try:
        import openai

        # Get API key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {
                "error": "OpenAI API key not configured",
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat(),
            }

        # Initialize OpenAI client
        client = openai.AsyncOpenAI(api_key=api_key)

        # Get conversation history from session storage
        conversation_history = get_conversation_history(conversation_id)

        # Default system prompt for software engineering
        if not system_prompt:
            system_prompt = """You are a helpful software engineering assistant. You specialize in:
- Programming languages (Python, JavaScript, Go, Rust, Java, C++, etc.)
- Software architecture and design patterns
- DevOps, CI/CD, and deployment strategies
- Debugging and troubleshooting
- Code review and best practices
- Framework and library recommendations
- Performance optimization
- Security considerations

Provide clear, practical, and actionable advice. Include code examples when helpful.
Keep responses concise but comprehensive."""

        # Build messages for OpenAI
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        # Get AI response
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        assistant_response = response.choices[0].message.content

        # Update conversation history
        conversation_history.append({"role": "user", "content": message})
        conversation_history.append(
            {"role": "assistant", "content": assistant_response}
        )
        store_conversation_history(conversation_id, conversation_history)

        return {
            "response": assistant_response,
            "conversation_id": conversation_id,
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "timestamp": datetime.now().isoformat(),
            "session_id": conversation_id,
            "agent": "software-chat-assistant",
        }

    except ImportError:
        return {
            "error": "OpenAI library not installed. Run: pip install openai",
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "error": f"Chat completion failed: {str(e)}",
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
        }


@app.tool()
@mesh.tool(
    capability="streaming_chat",
    tags=["chat", "ai", "software", "streaming"],
    session_required=True,
    stateful=True,
    streaming=True,
)
async def stream_chat_response(
    message: str,
    conversation_id: str,
    model: str = "gpt-4",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    system_prompt: Optional[str] = None,
) -> AsyncIterator[Dict]:
    """
    Stream chat response from AI assistant for real-time conversation.

    Uses Server-Sent Events (SSE) for streaming responses, perfect for
    interactive chat interfaces.
    """
    try:
        import openai

        # Get API key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            yield {
                "error": "OpenAI API key not configured",
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat(),
                "stream_end": True,
            }
            return

        # Initialize OpenAI client
        client = openai.AsyncOpenAI(api_key=api_key)

        # Get conversation history
        conversation_history = get_conversation_history(conversation_id)

        # Default system prompt
        if not system_prompt:
            system_prompt = """You are a helpful software engineering assistant. You specialize in:
- Programming languages and frameworks
- Software architecture and design
- DevOps and deployment
- Debugging and optimization
- Best practices and code review

Provide clear, practical advice with code examples when helpful."""

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        # Stream response
        full_response = ""
        async for chunk in await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        ):
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content

                yield {
                    "content": content,
                    "conversation_id": conversation_id,
                    "model": model,
                    "timestamp": datetime.now().isoformat(),
                    "stream_chunk": True,
                }

        # Update conversation history with complete response
        conversation_history.append({"role": "user", "content": message})
        conversation_history.append({"role": "assistant", "content": full_response})
        store_conversation_history(conversation_id, conversation_history)

        # Send final stream marker
        yield {
            "full_response": full_response,
            "conversation_id": conversation_id,
            "model": model,
            "timestamp": datetime.now().isoformat(),
            "stream_end": True,
        }

    except ImportError:
        yield {
            "error": "OpenAI library not installed. Run: pip install openai",
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
            "stream_end": True,
        }
    except Exception as e:
        yield {
            "error": f"Streaming chat failed: {str(e)}",
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
            "stream_end": True,
        }


@app.tool()
@mesh.tool(capability="new_conversation", tags=["chat", "session"])
def start_new_conversation(topic: Optional[str] = None) -> Dict:
    """Start a new conversation with optional topic context."""
    import uuid

    conversation_id = f"chat:{uuid.uuid4().hex[:16]}"

    # Initialize empty conversation
    store_conversation_history(conversation_id, [])

    return {
        "conversation_id": conversation_id,
        "topic": topic,
        "status": "started",
        "timestamp": datetime.now().isoformat(),
        "agent": "software-chat-assistant",
    }


@app.tool()
@mesh.tool(capability="conversation_history", tags=["chat", "session"])
def get_conversation_summary(conversation_id: str) -> Dict:
    """Get summary of conversation history."""
    history = get_conversation_history(conversation_id)

    message_count = len(history)
    user_messages = len([msg for msg in history if msg["role"] == "user"])
    assistant_messages = len([msg for msg in history if msg["role"] == "assistant"])

    return {
        "conversation_id": conversation_id,
        "total_messages": message_count,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "history": history[-10:],  # Last 10 messages
        "timestamp": datetime.now().isoformat(),
    }


@app.tool()
@mesh.tool(capability="clear_conversation", tags=["chat", "session"])
def clear_conversation(conversation_id: str) -> Dict:
    """Clear conversation history."""
    store_conversation_history(conversation_id, [])

    return {
        "conversation_id": conversation_id,
        "status": "cleared",
        "timestamp": datetime.now().isoformat(),
    }


# Helper functions for conversation storage
def get_conversation_history(conversation_id: str) -> List[Dict]:
    """Get conversation history from session storage."""
    # In-memory storage for demo (use Redis/database in production)
    if not hasattr(get_conversation_history, "_storage"):
        get_conversation_history._storage = {}

    return get_conversation_history._storage.get(conversation_id, [])


def store_conversation_history(conversation_id: str, history: List[Dict]) -> None:
    """Store conversation history in session storage."""
    if not hasattr(get_conversation_history, "_storage"):
        get_conversation_history._storage = {}

    # Limit history to last 20 messages to prevent memory bloat
    get_conversation_history._storage[conversation_id] = history[-20:]


# MCP PROMPTS - Templates for enhanced AI interactions
@app.prompt("software_code_review")
@mesh.tool(capability="code_review_prompt", tags=["prompt", "code", "review"])
def code_review_prompt(
    code: str, language: str = "python", focus_areas: str = "all"
) -> str:
    """
    Generate a comprehensive code review prompt for AI analysis.

    Focus areas: security, performance, readability, maintainability, testing, all
    """
    return f"""Please review the following {language} code and provide detailed feedback:

```{language}
{code}
```

**Review Focus**: {focus_areas}

**Please analyze:**
1. **Code Quality**: Readability, structure, naming conventions
2. **Best Practices**: Language-specific patterns and idioms
3. **Security**: Potential vulnerabilities or security concerns
4. **Performance**: Efficiency improvements and optimizations
5. **Maintainability**: How easy is this code to modify and extend
6. **Testing**: Suggestions for unit tests and edge cases
7. **Documentation**: Comments and docstring improvements

**Format your response with:**
- ✅ **Strengths**: What's done well
- ⚠️ **Issues**: Problems to address (with severity: Low/Medium/High)
- 🔧 **Suggestions**: Specific improvements with code examples
- 🧪 **Testing**: Test cases to consider

Be constructive and provide actionable feedback with code examples where helpful."""


@app.prompt("architecture_design")
@mesh.tool(capability="architecture_prompt", tags=["prompt", "architecture", "design"])
def architecture_design_prompt(
    system_description: str, scale: str = "medium", constraints: str = "none"
) -> str:
    """
    Generate architecture design prompt for system analysis.

    Scale: small, medium, large, enterprise
    """
    return f"""Design a software architecture for the following system:

**System Requirements:**
{system_description}

**Scale**: {scale}
**Constraints**: {constraints}

**Please provide:**

1. **High-Level Architecture**
   - System components and their responsibilities
   - Communication patterns between components
   - Data flow and processing pipeline

2. **Technology Stack Recommendations**
   - Programming languages and frameworks
   - Databases and storage solutions
   - Infrastructure and deployment options

3. **Scalability Considerations**
   - How the system handles growth
   - Bottlenecks and mitigation strategies
   - Performance optimization opportunities

4. **Security Architecture**
   - Authentication and authorization
   - Data protection and encryption
   - Security boundaries and trust zones

5. **Operational Concerns**
   - Monitoring and observability
   - Deployment and CI/CD pipeline
   - Disaster recovery and backup strategies

6. **Architecture Diagram**
   - Text-based diagram showing component relationships
   - API boundaries and data flows

**Format**: Provide clear, actionable recommendations with reasoning for each choice."""


@app.prompt("debugging_analysis")
@mesh.tool(
    capability="debugging_prompt", tags=["prompt", "debugging", "troubleshooting"]
)
def debugging_analysis_prompt(
    error_description: str, error_logs: str = "", system_context: str = ""
) -> str:
    """Generate debugging analysis prompt for systematic troubleshooting."""
    logs_section = f"\n**Error Logs:**\n```\n{error_logs}\n```\n" if error_logs else ""
    context_section = (
        f"\n**System Context:**\n{system_context}\n" if system_context else ""
    )

    return f"""Help debug the following issue using systematic troubleshooting:

**Problem Description:**
{error_description}
{logs_section}{context_section}

**Please provide a structured debugging approach:**

1. **Problem Analysis**
   - What the error likely indicates
   - Root cause hypotheses (most likely first)
   - Impact assessment

2. **Diagnostic Steps** (in order of priority)
   - Step-by-step investigation process
   - Commands or tools to gather more information
   - What to look for in each step

3. **Common Causes** for this type of issue
   - Configuration problems
   - Environment issues
   - Code-related causes
   - Infrastructure problems

4. **Solution Strategies**
   - Quick fixes to try first
   - Comprehensive solutions
   - Prevention measures for the future

5. **Verification Steps**
   - How to confirm the fix worked
   - Monitoring to prevent recurrence
   - Tests to validate the solution

**Format**: Provide actionable, prioritized steps with specific commands and tools where applicable."""


@app.prompt("performance_optimization")
@mesh.tool(
    capability="performance_prompt", tags=["prompt", "performance", "optimization"]
)
def performance_optimization_prompt(
    performance_issue: str, metrics: str = "", technology_stack: str = ""
) -> str:
    """Generate performance optimization analysis prompt."""
    metrics_section = f"\n**Current Metrics:**\n{metrics}\n" if metrics else ""
    stack_section = (
        f"\n**Technology Stack:**\n{technology_stack}\n" if technology_stack else ""
    )

    return f"""Analyze and optimize the following performance issue:

**Performance Problem:**
{performance_issue}
{metrics_section}{stack_section}

**Please provide comprehensive optimization guidance:**

1. **Performance Analysis**
   - Bottleneck identification
   - Performance metrics interpretation
   - Impact on user experience

2. **Optimization Strategies** (by impact/effort ratio)
   - **Quick Wins**: Low effort, high impact improvements
   - **Medium-term**: Moderate effort optimizations
   - **Long-term**: Architecture-level improvements

3. **Specific Optimizations**
   - Code-level optimizations
   - Database query improvements
   - Caching strategies
   - Infrastructure scaling

4. **Monitoring & Measurement**
   - Key metrics to track
   - Tools for performance monitoring
   - Benchmarking approaches

5. **Implementation Plan**
   - Prioritized action items
   - Risk assessment for each change
   - Rollback strategies

**Format**: Provide measurable, actionable recommendations with expected impact estimates."""


@app.tool()
@mesh.tool(capability="software_knowledge_search", tags=["search", "knowledge"])
def search_software_knowledge(
    query: str, category: str = "general", max_results: int = 5
) -> Dict:
    """
    Search software engineering knowledge base.

    Categories: programming, architecture, devops, debugging, frameworks, security
    """
    # Simple knowledge base for demo
    knowledge_base = {
        "programming": {
            "python best practices": "Use virtual environments, follow PEP 8, write tests, use type hints",
            "javascript async": "Use async/await for better readability over Promises, handle errors with try/catch",
            "go concurrency": "Use goroutines and channels, avoid shared state, prefer CSP model",
            "rust memory safety": "Ownership system prevents memory leaks, use borrowing, avoid unsafe code",
        },
        "architecture": {
            "microservices": "Independent deployable services, API-first design, eventual consistency",
            "event driven": "Publish-subscribe patterns, event sourcing, CQRS for complex domains",
            "clean architecture": "Dependency inversion, use cases, infrastructure independence",
        },
        "devops": {
            "ci/cd": "Automate testing, use feature flags, deploy small changes frequently",
            "monitoring": "Use metrics, logs, traces (observability), set up alerting",
            "docker": "Multi-stage builds, minimal base images, .dockerignore for efficiency",
        },
        "debugging": {
            "performance": "Profile first, optimize bottlenecks, measure improvements",
            "memory leaks": "Use profilers, check for circular references, monitor heap growth",
            "network issues": "Check DNS, timeouts, retries, circuit breakers",
        },
    }

    # Simple search
    results = []
    search_category = category.lower()

    if search_category in knowledge_base:
        for topic, info in knowledge_base[search_category].items():
            if query.lower() in topic.lower() or query.lower() in info.lower():
                results.append(
                    {
                        "topic": topic,
                        "information": info,
                        "category": search_category,
                        "relevance": (
                            "high" if query.lower() in topic.lower() else "medium"
                        ),
                    }
                )

    # Limit results
    results = results[:max_results]

    return {
        "query": query,
        "category": category,
        "results": results,
        "count": len(results),
        "timestamp": datetime.now().isoformat(),
    }


@app.tool()
@mesh.tool(
    capability="enhanced_chat_with_prompts",
    tags=["chat", "ai", "prompts", "enhanced"],
    session_required=True,
    stateful=True,
)
async def enhanced_chat_with_prompts(
    user_input: str,
    conversation_id: str,
    prompt_type: str = "general",
    context_data: Optional[str] = None,
    model: str = "gpt-4",
    temperature: float = 0.7,
) -> Dict:
    """
    Enhanced chat using MCP prompt decoration for specialized responses.

    prompt_type: general, code_review, architecture, debugging, performance
    """
    try:
        import openai

        # Get API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {
                "error": "OpenAI API key not configured",
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat(),
            }

        client = openai.AsyncOpenAI(api_key=api_key)

        # Generate specialized prompt based on type
        enhanced_prompt = ""
        if prompt_type == "code_review" and context_data:
            enhanced_prompt = code_review_prompt(
                code=context_data,
                language="python",  # Could be detected
                focus_areas="all",
            )
        elif prompt_type == "architecture" and context_data:
            enhanced_prompt = architecture_design_prompt(
                system_description=context_data, scale="medium", constraints="none"
            )
        elif prompt_type == "debugging" and context_data:
            enhanced_prompt = debugging_analysis_prompt(
                error_description=user_input, error_logs=context_data, system_context=""
            )
        elif prompt_type == "performance" and context_data:
            enhanced_prompt = performance_optimization_prompt(
                performance_issue=user_input, metrics=context_data, technology_stack=""
            )
        else:
            # General chat - use standard system prompt
            enhanced_prompt = user_input

        # Get conversation history
        conversation_history = get_conversation_history(conversation_id)

        # Build messages with enhanced prompt
        if prompt_type != "general":
            # Use the MCP prompt as the user message
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful software engineering assistant. Provide detailed, actionable responses.",
                },
                *conversation_history,
                {"role": "user", "content": enhanced_prompt},
            ]
        else:
            # Standard conversation flow
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful software engineering assistant.",
                },
                *conversation_history,
                {"role": "user", "content": user_input},
            ]

        # Get AI response
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=3000,  # More tokens for detailed analysis
        )

        assistant_response = response.choices[0].message.content

        # Update conversation history
        if prompt_type != "general":
            # Store the original user input, not the enhanced prompt
            conversation_history.append(
                {"role": "user", "content": f"[{prompt_type.upper()}] {user_input}"}
            )
        else:
            conversation_history.append({"role": "user", "content": user_input})

        conversation_history.append(
            {"role": "assistant", "content": assistant_response}
        )
        store_conversation_history(conversation_id, conversation_history)

        return {
            "response": assistant_response,
            "conversation_id": conversation_id,
            "prompt_type": prompt_type,
            "enhanced_prompt_used": prompt_type != "general",
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Enhanced chat failed: {str(e)}",
            "conversation_id": conversation_id,
            "prompt_type": prompt_type,
            "timestamp": datetime.now().isoformat(),
        }


# AGENT configuration
@mesh.agent(
    name="software-chat-assistant",
    version="1.0.0",
    description="AI-powered software engineering chat assistant with streaming support",
    http_port=9094,
    enable_http=True,
    auto_run=True,
)
class SoftwareChatAssistant:
    """
    AI chat agent specialized in software engineering.

    Features:
    - OpenAI GPT integration for intelligent responses
    - Streaming chat with Server-Sent Events
    - Session-based conversation management
    - Software engineering knowledge base
    - MCP protocol compliance
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - OpenAI API integration
# - Streaming response handling
# - Session management
# - Service registration with mesh registry

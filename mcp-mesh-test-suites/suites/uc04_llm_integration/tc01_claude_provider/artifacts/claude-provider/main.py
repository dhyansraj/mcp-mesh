"""
Claude Provider Agent for LLM Integration Testing.

A simple MCP Mesh provider that uses Claude to answer questions.
Exposes an 'ask_claude' tool that sends prompts to Claude.
"""

import os
from mcpmesh import Provider


provider = Provider(
    name="claude-provider",
    description="A provider that uses Claude to answer questions",
)


@provider.tool(
    description="Ask Claude a question and get a response",
)
def ask_claude(question: str, max_tokens: int = 500) -> str:
    """
    Send a question to Claude and return the response.

    Args:
        question: The question to ask Claude
        max_tokens: Maximum tokens in the response (default: 500)

    Returns:
        Claude's response text
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY environment variable not set"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": question}],
        )

        if response.content:
            return response.content[0].text
        return "No response content"

    except Exception as e:
        return f"Error calling Claude: {str(e)}"


@provider.tool(
    description="Simple math calculation (for testing without API)",
)
def calculate(expression: str) -> str:
    """
    Evaluate a simple math expression.

    Args:
        expression: Math expression like "2 + 2" or "10 * 5"

    Returns:
        The result of the calculation
    """
    try:
        # Safe eval for simple math expressions
        allowed_chars = set("0123456789+-*/(). ")
        if not all(c in allowed_chars for c in expression):
            return "Error: Invalid characters in expression"

        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    provider.run()

"""
OpenAI Provider Agent for LLM Integration Testing.

A simple MCP Mesh provider that uses OpenAI to answer questions.
Exposes an 'ask_gpt' tool that sends prompts to GPT models.
"""

import os
from mcpmesh import Provider


provider = Provider(
    name="openai-provider",
    description="A provider that uses OpenAI GPT to answer questions",
)


@provider.tool(
    description="Ask GPT a question and get a response",
)
def ask_gpt(question: str, max_tokens: int = 500) -> str:
    """
    Send a question to GPT and return the response.

    Args:
        question: The question to ask GPT
        max_tokens: Maximum tokens in the response (default: 500)

    Returns:
        GPT's response text
    """
    import openai

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Error: OPENAI_API_KEY environment variable not set"

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": question}],
        )

        if response.choices:
            return response.choices[0].message.content or "No content"
        return "No response choices"

    except Exception as e:
        return f"Error calling OpenAI: {str(e)}"


@provider.tool(
    description="Simple string operation (for testing without API)",
)
def reverse_string(text: str) -> str:
    """
    Reverse a string.

    Args:
        text: The text to reverse

    Returns:
        The reversed text
    """
    return text[::-1]


if __name__ == "__main__":
    provider.run()

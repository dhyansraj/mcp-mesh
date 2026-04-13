# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP

app = FastMCP("Claude Provider")
# --8<-- [end:imports]


# --8<-- [start:provider_function]
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["claude"],
    version="1.0.0",
)
def claude_provider():
    """Zero-code LLM provider. Wraps the Claude API as a mesh capability."""
    pass
# --8<-- [end:provider_function]


@mesh.agent(
    name="claude-provider",
    version="1.0.0",
    description="TripPlanner Claude LLM provider (Day 7)",
    http_port=9106,
    enable_http=True,
    auto_run=True,
)
class ClaudeProviderAgent:
    pass
# --8<-- [end:full_file]

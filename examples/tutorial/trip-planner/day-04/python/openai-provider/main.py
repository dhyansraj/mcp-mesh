# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP

app = FastMCP("OpenAI Provider")
# --8<-- [end:imports]


# --8<-- [start:provider_function]
@mesh.llm_provider(
    model="openai/gpt-4o-mini",
    capability="llm",
    tags=["openai", "gpt"],
    version="1.0.0",
)
def openai_provider():
    """Zero-code LLM provider. Wraps the OpenAI API as a mesh capability."""
    pass
# --8<-- [end:provider_function]


@mesh.agent(
    name="openai-provider",
    version="1.0.0",
    description="TripPlanner OpenAI LLM provider (Day 4)",
    http_port=9108,
    enable_http=True,
    auto_run=True,
)
class OpenaiProviderAgent:
    pass
# --8<-- [end:full_file]

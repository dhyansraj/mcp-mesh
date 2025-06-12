FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx

# Create a simple MCP agent for testing
RUN echo 'from fastapi import FastAPI\n\
import os\n\
import json\n\
\n\
app = FastAPI()\n\
\n\
@app.get("/health")\n\
async def health():\n\
    return {"status": "healthy", "agent": os.environ.get("AGENT_NAME", "test-agent")}\n\
\n\
@app.get("/ready")\n\
async def ready():\n\
    return {"ready": True, "tools_count": 1}\n\
\n\
@app.get("/livez")\n\
async def liveness():\n\
    return {"alive": True}\n\
\n\
@app.get("/mesh/info")\n\
async def mesh_info():\n\
    return {\n\
        "agent_id": os.environ.get("AGENT_NAME", "test-agent"),\n\
        "capabilities": ["greeting"],\n\
        "dependencies": [],\n\
        "transport": ["http"],\n\
        "http_endpoint": "http://" + os.environ.get("POD_IP", "localhost") + ":8080"\n\
    }\n\
\n\
@app.post("/mcp")\n\
async def mcp_handler(request: dict):\n\
    method = request.get("method")\n\
    if method == "tools/list":\n\
        return {\n\
            "tools": [{\n\
                "name": "greet",\n\
                "description": "Greet someone",\n\
                "inputSchema": {\n\
                    "type": "object",\n\
                    "properties": {\n\
                        "name": {"type": "string"}\n\
                    },\n\
                    "required": ["name"]\n\
                }\n\
            }]\n\
        }\n\
    elif method == "tools/call":\n\
        name = request.get("params", {}).get("arguments", {}).get("name", "World")\n\
        return {\n\
            "content": [{"type": "text", "text": f"Hello, {name}!"}],\n\
            "isError": False\n\
        }\n\
    return {"error": "Unknown method"}\n\
\n\
if __name__ == "__main__":\n\
    import uvicorn\n\
    uvicorn.run(app, host="0.0.0.0", port=8080)\n\
' > /app/agent.py

# Create directories
RUN mkdir -p /data /etc/mcp-mesh

# Non-root user
RUN useradd -m -u 1000 mcp && \
    chown -R mcp:mcp /app /data /etc/mcp-mesh

USER mcp

EXPOSE 8080

CMD ["python", "/app/agent.py"]

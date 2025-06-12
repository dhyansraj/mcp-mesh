FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy registry source code (placeholder for now)
RUN mkdir -p /app/mcp_mesh_registry

# Create a simple registry server for testing
RUN echo 'from http.server import HTTPServer, BaseHTTPRequestHandler\n\
import json\n\
import os\n\
\n\
class RegistryHandler(BaseHTTPRequestHandler):\n\
    def do_GET(self):\n\
        if self.path == "/health":\n\
            self.send_response(200)\n\
            self.send_header("Content-type", "application/json")\n\
            self.end_headers()\n\
            self.wfile.write(json.dumps({"status": "healthy"}).encode())\n\
        elif self.path == "/ready":\n\
            self.send_response(200)\n\
            self.send_header("Content-type", "application/json")\n\
            self.end_headers()\n\
            self.wfile.write(json.dumps({"ready": True}).encode())\n\
        elif self.path == "/api/v1/agents":\n\
            self.send_response(200)\n\
            self.send_header("Content-type", "application/json")\n\
            self.end_headers()\n\
            self.wfile.write(json.dumps({"agents": []}).encode())\n\
        else:\n\
            self.send_response(404)\n\
            self.end_headers()\n\
\n\
if __name__ == "__main__":\n\
    server = HTTPServer(("0.0.0.0", 8080), RegistryHandler)\n\
    print("Registry server starting on port 8080...")\n\
    server.serve_forever()\n\
' > /app/server.py

# Create directories
RUN mkdir -p /data /etc/mcp-mesh

# Non-root user
RUN useradd -m -u 1000 mcp && \
    chown -R mcp:mcp /app /data /etc/mcp-mesh

USER mcp

EXPOSE 8080 9090

CMD ["python", "/app/server.py"]

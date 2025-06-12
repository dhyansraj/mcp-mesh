# Docker Deployment

> Package and run MCP Mesh agents in containers for consistent, portable deployments

## Overview

Docker provides a consistent environment for running MCP Mesh agents across different systems. This section covers building Docker images for your agents, running multi-agent systems with Docker Compose, and preparing for container orchestration platforms.

Whether you're containerizing a single agent or building a complex multi-service mesh, Docker ensures your agents run the same way everywhere - from your laptop to production servers.

## What You'll Learn

By the end of this section, you will:

- ✅ Build optimized Docker images for MCP Mesh agents
- ✅ Configure multi-agent systems with Docker Compose
- ✅ Implement service discovery in containerized environments
- ✅ Manage persistent data and configuration
- ✅ Set up networking for agent communication
- ✅ Prepare for Kubernetes deployment

## Why Docker for MCP Mesh?

Docker solves several challenges in distributed agent deployment:

1. **Consistency**: Same environment everywhere, no "works on my machine"
2. **Isolation**: Agents run in separate containers with defined resources
3. **Portability**: Move from development to production seamlessly
4. **Scalability**: Easy to run multiple instances of agents
5. **Dependency Management**: All dependencies packaged with the agent

## Docker Architecture for MCP Mesh

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Host                               │
│                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │  Registry        │  │  Weather Agent   │  │  System     │ │
│  │  Container       │  │  Container       │  │  Agent      │ │
│  │                  │  │                  │  │  Container  │ │
│  │  ┌─────────────┐ │  │  ┌─────────────┐ │  │  ┌────────┐│ │
│  │  │ Go Registry │ │  │  │ Python Agent│ │  │  │ Python ││ │
│  │  │ PostgreSQL  │ │  │  │ MCP Mesh    │ │  │  │ Agent  ││ │
│  │  └─────────────┘ │  │  └─────────────┘ │  │  └────────┘│ │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬─────┘ │
│           │                      │                    │       │
│  ┌────────┴──────────────────────┴────────────────────┴────┐ │
│  │                   Docker Network (mesh-net)              │ │
│  └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Section Contents

1. **[Building Docker Images](./03-docker-deployment/01-building-images.md)** - Create optimized images for agents
2. **[Docker Compose Setup](./03-docker-deployment/02-compose-setup.md)** - Orchestrate multi-agent systems
3. **[Multi-Agent Deployment](./03-docker-deployment/03-multi-agent.md)** - Run complex agent networks
4. **[Networking and Service Discovery](./03-docker-deployment/04-networking.md)** - Container communication
5. **[Persistent Storage](./03-docker-deployment/05-storage.md)** - Data persistence strategies

## Quick Start Example

Here's a complete Docker Compose setup to get you started:

```yaml
# docker-compose.yml
version: "3.8"

services:
  registry:
    build:
      context: .
      dockerfile: docker/registry/Dockerfile
    ports:
      - "8080:8080"
    environment:
      MCP_MESH_DB_TYPE: postgresql
      MCP_MESH_DB_HOST: postgres
      MCP_MESH_DB_NAME: mcp_mesh
      MCP_MESH_DB_USER: postgres
      MCP_MESH_DB_PASSWORD: postgres
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: mcp_mesh
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  system-agent:
    build:
      context: .
      dockerfile: docker/agent/Dockerfile
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8080
      AGENT_FILE: examples/system_agent.py
    depends_on:
      - registry

  weather-agent:
    build:
      context: .
      dockerfile: docker/agent/Dockerfile
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8080
      AGENT_FILE: examples/weather_agent.py
    depends_on:
      - registry
      - system-agent

volumes:
  postgres_data:

networks:
  default:
    name: mesh-net
```

Run it with:

```bash
docker-compose up -d
docker-compose logs -f
```

## Key Concepts for Docker Deployment

### 1. Image Layers and Caching

Build efficient images with proper layering:

```dockerfile
# Good: Layers that change less frequently first
FROM python:3.11-slim
WORKDIR /app

# Dependencies layer (changes rarely)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application layer (changes frequently)
COPY . .
CMD ["python", "agent.py"]
```

### 2. Environment Configuration

Use environment variables for configuration:

```bash
# Development
docker run -e MCP_MESH_LOG_LEVEL=DEBUG my-agent

# Production
docker run -e MCP_MESH_LOG_LEVEL=INFO my-agent
```

### 3. Health Checks

Ensure containers are ready before dependent services start:

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import requests; requests.get('http://localhost:8888/health')"
```

## Development Workflow with Docker

1. **Build Once, Run Anywhere**

   ```bash
   docker build -t my-agent:latest .
   docker run my-agent:latest
   ```

2. **Local Development with Bind Mounts**

   ```bash
   docker run -v $(pwd)/agents:/app/agents my-agent:latest
   ```

3. **Multi-Stage Builds for Optimization**

   ```dockerfile
   FROM python:3.11 AS builder
   # Build stage

   FROM python:3.11-slim
   # Runtime stage
   ```

## Best Practices

- 🔒 **Security**: Never embed secrets in images
- 📦 **Size**: Use slim base images and multi-stage builds
- 🏷️ **Tagging**: Use semantic versioning for image tags
- 📝 **Documentation**: Include README in image with usage instructions
- 🔄 **Updates**: Regularly update base images for security patches

## Ready to Start?

Begin with [Building Docker Images](./03-docker-deployment/01-building-images.md) →

## 🔧 Troubleshooting

### Common Docker Issues

1. **Container can't connect to registry**

   - Check network configuration
   - Verify service names in compose file
   - Ensure registry is healthy before agents start

2. **Agent exits immediately**

   - Check logs: `docker logs <container>`
   - Verify CMD or ENTRYPOINT is correct
   - Ensure required environment variables are set

3. **Permission denied errors**
   - Run containers as non-root user
   - Check file permissions in image
   - Use proper volume mount permissions

For detailed solutions, see our [Docker Troubleshooting Guide](./03-docker-deployment/troubleshooting.md).

## ⚠️ Known Limitations

- **Windows Containers**: Limited support, use Linux containers
- **ARM Architecture**: Some base images may not support ARM
- **File Watching**: Hot reload doesn't work well in containers
- **Networking**: Container networking adds complexity to debugging

## 📝 TODO

- [ ] Add Kubernetes deployment examples
- [ ] Create automated image vulnerability scanning
- [ ] Add examples for cloud container registries
- [ ] Document multi-architecture builds
- [ ] Add container security best practices guide

---

💡 **Tip**: Use Docker BuildKit for faster builds: `DOCKER_BUILDKIT=1 docker build .`

📚 **Reference**: [Official Docker Documentation](https://docs.docker.com/)

🎯 **Next Step**: Ready to containerize your agents? Start with [Building Docker Images](./03-docker-deployment/01-building-images.md)

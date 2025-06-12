# Docker Deployment Troubleshooting Guide

> Quick solutions to common Docker deployment issues with MCP Mesh

## Overview

This comprehensive troubleshooting guide addresses common issues encountered when deploying MCP Mesh agents with Docker. Each issue includes diagnostic steps, root cause analysis, and proven solutions.

## Quick Diagnostics

Run this comprehensive diagnostic script:

```bash
#!/bin/bash
echo "MCP Mesh Docker Diagnostics"
echo "==========================="

# Check Docker daemon
echo -n "Docker daemon: "
docker version > /dev/null 2>&1 && echo "RUNNING" || echo "NOT RUNNING"

# Check Docker Compose
echo -n "Docker Compose: "
docker-compose version > /dev/null 2>&1 && echo "INSTALLED" || echo "NOT FOUND"

# Check running containers
echo -e "\nRunning containers:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check networks
echo -e "\nDocker networks:"
docker network ls --filter name=mesh

# Check volumes
echo -e "\nDocker volumes:"
docker volume ls --filter name=mesh

# Check resource usage
echo -e "\nResource usage:"
docker system df

# Check container health
echo -e "\nContainer health:"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(healthy|unhealthy|starting)"

# Check registry connectivity
echo -e "\nRegistry status:"
curl -s http://localhost:8080/health 2>/dev/null | jq -r '.status' || echo "NOT ACCESSIBLE"
```

## Common Issues and Solutions

### Issue 1: Container Fails to Start

**Symptoms:**

```
ERROR: for agent Cannot start service agent: OCI runtime create failed
```

**Diagnosis:**

```bash
# Check logs
docker-compose logs agent

# Inspect container
docker inspect $(docker-compose ps -q agent)

# Check events
docker events --since 10m --filter container=agent
```

**Solutions:**

1. **Image not found:**

   ```bash
   # Build missing image
   docker-compose build agent

   # Or pull from registry
   docker-compose pull agent
   ```

2. **Port already in use:**

   ```bash
   # Find process using port
   sudo lsof -i :8080

   # Change port in docker-compose.yml
   ports:
     - "8081:8080"  # Use different host port
   ```

3. **Permission issues:**
   ```dockerfile
   # Fix in Dockerfile
   RUN chmod +x /entrypoint.sh
   USER 1000:1000
   ```

### Issue 2: Agent Can't Connect to Registry

**Symptoms:**

```
Failed to register with registry: connection refused
Registry at http://localhost:8080 not accessible
```

**Diagnosis:**

```bash
# Test from host
curl http://localhost:8080/health

# Test from container
docker-compose exec agent curl http://registry:8080/health

# Check DNS resolution
docker-compose exec agent nslookup registry
```

**Solutions:**

1. **Wrong hostname:**

   ```yaml
   environment:
     # Use service name, not localhost
     MCP_MESH_REGISTRY_URL: http://registry:8080
   ```

2. **Network isolation:**

   ```yaml
   services:
     agent:
       networks:
         - mesh-net # Same network as registry
     registry:
       networks:
         - mesh-net
   ```

3. **Startup order:**
   ```yaml
   depends_on:
     registry:
       condition: service_healthy
   ```

### Issue 3: Database Connection Errors

**Symptoms:**

```
FATAL: password authentication failed for user "postgres"
could not connect to server: Connection refused
```

**Solutions:**

1. **Environment variables not set:**

   ```yaml
   # Use .env file
   environment:
     POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

   # Or docker-compose override
   docker-compose run -e POSTGRES_PASSWORD=secret postgres
   ```

2. **Database not initialized:**

   ```bash
   # Remove old volume and reinitialize
   docker-compose down -v
   docker volume rm project_postgres_data
   docker-compose up -d postgres
   ```

3. **Health check timing:**
   ```yaml
   healthcheck:
     test: ["CMD-SHELL", "pg_isready -U postgres"]
     interval: 10s
     timeout: 5s
     retries: 5
     start_period: 30s # Give time to initialize
   ```

### Issue 4: Container Keeps Restarting

**Symptoms:**

```
STATUS: Restarting (1) X seconds ago
Container exits immediately after starting
```

**Diagnosis:**

```bash
# Check exit code
docker-compose ps

# View recent logs
docker-compose logs --tail=50 agent

# Check restart policy
docker inspect agent | jq '.[0].HostConfig.RestartPolicy'
```

**Solutions:**

1. **Application crashes:**

   ```yaml
   # Temporarily disable restart
   restart: "no"

   # Run interactively to debug
   docker-compose run --rm agent bash
   ```

2. **Missing environment variables:**

   ```yaml
   environment:
     - REQUIRED_VAR=${REQUIRED_VAR:?Error: REQUIRED_VAR not set}
   ```

3. **Entrypoint issues:**
   ```dockerfile
   # Use exec form to handle signals properly
   ENTRYPOINT ["python", "-m", "mcp_mesh.cli"]
   CMD ["start", "agent.py"]
   ```

### Issue 5: Out of Memory Errors

**Symptoms:**

```
Container killed due to OOM (Out of Memory)
Agent becomes unresponsive
```

**Solutions:**

1. **Set memory limits:**

   ```yaml
   deploy:
     resources:
       limits:
         memory: 512M
       reservations:
         memory: 256M
   ```

2. **Optimize application:**

   ```python
   # In agent code
   import gc

   def process_large_data():
       # Process in chunks
       for chunk in data_chunks:
           process(chunk)
           gc.collect()  # Force garbage collection
   ```

3. **Monitor memory usage:**

   ```bash
   # Real-time monitoring
   docker stats

   # Historical data
   docker-compose exec agent cat /proc/meminfo
   ```

### Issue 6: Volume Permission Issues

**Symptoms:**

```
Permission denied when writing to volume
Cannot create directory: Operation not permitted
```

**Solutions:**

1. **Fix ownership:**

   ```bash
   # Check current ownership
   docker-compose exec agent ls -la /data

   # Fix from host
   sudo chown -R 1000:1000 ./data

   # Or use init container
   services:
     init-permissions:
       image: busybox
       volumes:
         - data:/data
       command: chown -R 1000:1000 /data
   ```

2. **Use proper user in container:**
   ```dockerfile
   # Create user with specific UID
   RUN useradd -m -u 1000 appuser
   USER appuser
   ```

### Issue 7: Slow Container Startup

**Symptoms:**

- Container takes minutes to become ready
- Health checks timing out

**Solutions:**

1. **Optimize image:**

   ```dockerfile
   # Multi-stage build
   FROM python:3.11 AS builder
   COPY requirements.txt .
   RUN pip wheel --no-cache-dir -r requirements.txt

   FROM python:3.11-slim
   COPY --from=builder *.whl .
   RUN pip install --no-cache-dir *.whl
   ```

2. **Adjust health check timing:**

   ```yaml
   healthcheck:
     start_period: 60s # Allow more startup time
     interval: 30s
     timeout: 10s
   ```

3. **Pre-compile Python:**
   ```dockerfile
   RUN python -m compileall /app
   ```

### Issue 8: Network Communication Issues

**Symptoms:**

- Containers can't reach each other
- DNS resolution failures
- Intermittent connection errors

**Solutions:**

1. **DNS debugging:**

   ```bash
   # Test DNS from container
   docker-compose exec agent nslookup registry
   docker-compose exec agent ping -c 3 registry

   # Check resolv.conf
   docker-compose exec agent cat /etc/resolv.conf
   ```

2. **Network inspection:**

   ```bash
   # List networks
   docker network ls

   # Inspect network
   docker network inspect mesh-net

   # Check container networks
   docker inspect agent | jq '.[0].NetworkSettings.Networks'
   ```

3. **Fix network configuration:**
   ```yaml
   networks:
     mesh-net:
       driver: bridge
       driver_opts:
         com.docker.network.bridge.enable_icc: "true"
         com.docker.network.bridge.enable_ip_masquerade: "true"
   ```

### Issue 9: Build Failures

**Symptoms:**

```
ERROR: Service 'agent' failed to build
Package installation fails
```

**Solutions:**

1. **Clear build cache:**

   ```bash
   # Remove all build cache
   docker builder prune -a

   # Build without cache
   docker-compose build --no-cache agent
   ```

2. **Fix package sources:**

   ```dockerfile
   # Update package lists
   RUN apt-get update && apt-get install -y ...

   # Use specific package versions
   RUN pip install package==1.2.3
   ```

3. **Handle network issues:**
   ```dockerfile
   # Retry on failure
   RUN for i in 1 2 3; do \
       pip install -r requirements.txt && break || sleep 5; \
   done
   ```

### Issue 10: Docker Compose Version Issues

**Symptoms:**

```
ERROR: Version in "./docker-compose.yml" is unsupported
Invalid compose file
```

**Solutions:**

1. **Check Docker Compose version:**

   ```bash
   docker-compose version

   # Upgrade if needed
   sudo pip install --upgrade docker-compose
   ```

2. **Use compatible syntax:**

   ```yaml
   # Use version 3.8 features carefully
   version: '3.8'

   # Or downgrade to widely supported version
   version: '3.3'
   ```

## Performance Issues

### High CPU Usage

```bash
# Find CPU-hungry containers
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}"

# Limit CPU usage
services:
  agent:
    deploy:
      resources:
        limits:
          cpus: '0.5'
```

### Disk Space Issues

```bash
# Check disk usage
docker system df

# Clean up
docker system prune -a --volumes

# Remove specific items
docker container prune
docker image prune
docker volume prune
docker network prune
```

## Emergency Recovery

### Complete Reset

```bash
#!/bin/bash
# emergency-reset.sh

echo "WARNING: This will delete all Docker data!"
read -p "Continue? (y/N) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Stop all containers
    docker-compose down

    # Remove all containers
    docker rm -f $(docker ps -aq) 2>/dev/null

    # Remove all images
    docker rmi -f $(docker images -q) 2>/dev/null

    # Remove all volumes
    docker volume rm $(docker volume ls -q) 2>/dev/null

    # Remove all networks
    docker network rm $(docker network ls -q) 2>/dev/null

    # Restart Docker
    sudo systemctl restart docker

    echo "Docker reset complete"
fi
```

### Backup Before Troubleshooting

```bash
#!/bin/bash
# backup-docker-state.sh

BACKUP_DIR="docker-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Export compose configuration
docker-compose config > "$BACKUP_DIR/docker-compose.resolved.yml"

# Save running container state
docker ps -a > "$BACKUP_DIR/containers.txt"

# Export volumes
for volume in $(docker volume ls -q); do
    docker run --rm -v $volume:/data -v $(pwd)/$BACKUP_DIR:/backup \
        busybox tar czf /backup/$volume.tar.gz /data
done

echo "Backup saved to $BACKUP_DIR"
```

## Getting Help

If these solutions don't resolve your issue:

1. **Collect diagnostic information:**

   ```bash
   docker-compose logs > docker-logs.txt
   docker-compose ps > docker-status.txt
   docker-compose config > docker-config.txt
   docker version > docker-version.txt
   ```

2. **Check GitHub issues:**

   - https://github.com/anthropics/mcp-mesh/issues

3. **Community support:**
   - MCP Discord: https://discord.gg/mcp
   - Stack Overflow: Tag with `mcp-mesh` and `docker`

---

💡 **Tip**: Always test solutions in a development environment first

📚 **Reference**: [Docker Troubleshooting Guide](https://docs.docker.com/config/troubleshoot/)

🔍 **Debug Mode**: Set `COMPOSE_DEBUG=true` for verbose Docker Compose output

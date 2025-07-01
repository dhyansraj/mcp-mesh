# Networking and Service Discovery

> Configure container networking for reliable agent communication and service discovery in Docker

## Overview

Networking is critical for MCP Mesh agents to discover and communicate with each other. This guide covers Docker networking concepts, DNS-based service discovery, network isolation strategies, and troubleshooting connectivity issues in containerized environments.

We'll explore how MCP Mesh's registry works with Docker networks, implement secure network topologies, and optimize network performance for agent communication.

## Key Concepts

- **Docker Networks**: Bridge, overlay, and custom network drivers
- **Service Discovery**: How containers find each other by name
- **Network Isolation**: Segmenting agents for security
- **Port Management**: Exposing services safely
- **DNS Resolution**: Container name resolution in Docker

## Step-by-Step Guide

### Step 1: Understanding Docker Networks for MCP Mesh

Create a dedicated network for your mesh:

```bash
# Create a custom bridge network
docker network create --driver bridge mcp-mesh-net

# With custom subnet
docker network create \
  --driver bridge \
  --subnet=172.20.0.0/16 \
  --ip-range=172.20.240.0/20 \
  --gateway=172.20.0.1 \
  mcp-mesh-net

# Inspect the network
docker network inspect mcp-mesh-net
```

Docker Compose network configuration:

```yaml
# docker-compose.yml
version: "3.8"

networks:
  mesh-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
    driver_opts:
      com.docker.network.bridge.name: br-mesh

  internal-net:
    driver: bridge
    internal: true # No external access

services:
  registry:
    image: mcp-mesh/registry:latest
    networks:
      mesh-net:
        ipv4_address: 172.20.0.10 # Fixed IP
    hostname: registry
    domainname: mesh.local
```

### Step 2: Configure Service Discovery

Enable container DNS resolution:

```yaml
# docker-compose.yml
version: "3.8"

services:
  registry:
    image: mcp-mesh/registry:latest
    hostname: registry # Other containers can reach via 'registry'
    networks:
      - mesh-net
    environment:
      MCP_MESH_PUBLIC_URL: http://registry:8000

  weather-agent:
    image: mcp-mesh/agent:0.2
    networks:
      - mesh-net
    environment:
      # Use service name for discovery
      MCP_MESH_REGISTRY_URL: http://registry:8000
    depends_on:
      - registry

  database-agent:
    image: mcp-mesh/agent:0.2
    networks:
      - mesh-net
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
      # Agents discover each other through registry
      MCP_MESH_ADVERTISE_HOST: database-agent
      MCP_MESH_ADVERTISE_PORT: 8081
```

Implement custom DNS with dnsmasq:

```yaml
# docker-compose.dns.yml
services:
  dnsmasq:
    image: strm/dnsmasq
    volumes:
      - ./dnsmasq.conf:/etc/dnsmasq.conf
    cap_add:
      - NET_ADMIN
    networks:
      mesh-net:
        ipv4_address: 172.20.0.2

  # Configure agents to use custom DNS
  agent:
    dns:
      - 172.20.0.2 # Custom DNS
      - 8.8.8.8 # Fallback
```

### Step 3: Implement Network Isolation

Separate agents by security zones:

```yaml
# docker-compose.secure.yml
version: "3.8"

networks:
  dmz: # Public-facing agents
    driver: bridge

  app: # Business logic agents
    driver: bridge
    internal: true

  data: # Database and storage agents
    driver: bridge
    internal: true

services:
  # DMZ Zone - Public facing
  api-gateway:
    image: mcp-mesh/agent:0.2
    networks:
      - dmz
      - app # Can talk to app tier
    ports:
      - "443:443"
    environment:
      ZONE: dmz

  # Application Zone - Business logic
  order-agent:
    image: mcp-mesh/agent:0.2
    networks:
      - app
      - data # Can talk to data tier
    environment:
      ZONE: app

  # Data Zone - Sensitive data
  database-agent:
    image: mcp-mesh/agent:0.2
    networks:
      - data # Only in data network
    environment:
      ZONE: data
      RESTRICT_ACCESS: "true"

  # Registry spans all zones
  registry:
    image: mcp-mesh/registry:latest
    networks:
      - dmz
      - app
      - data
```

### Step 4: Configure Agent Communication

Set up proper agent networking:

```python
# agents/network_aware_agent.py
import os
import socket
import mesh

def get_container_ip():
    """Get container's IP address"""
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    return ip

@mesh.agent(name="network-aware")
class NetworkAwareAgent:
    pass

@mesh.tool(
    capability="network_aware_service"
)
def network_service():
    return {
        "hostname": socket.gethostname(),
        "ip": get_container_ip(),
        "fqdn": socket.getfqdn(),
        "network_zone": os.getenv('ZONE', 'default')
    }
```

Configure network policies in agents:

```yaml
# agent-config.yml
network:
  discovery:
    # Use Docker's embedded DNS
    use_dns: true
    dns_suffix: ".mesh.local"

  communication:
    # Prefer internal networks
    prefer_private_ip: true

    # Network interface selection
    interface_priority:
      - eth0 # Docker network
      - eth1 # Secondary network

  security:
    # Only accept connections from same network
    network_whitelist:
      - 172.20.0.0/16

    # TLS for cross-zone communication
    require_tls:
      - dmz->app
      - app->data
```

## Configuration Options

| Option                     | Description               | Default            | Example            |
| -------------------------- | ------------------------- | ------------------ | ------------------ |
| `MCP_MESH_ADVERTISE_HOST`  | Hostname/IP to advertise  | container hostname | agent-1.mesh.local |
| `MCP_MESH_ADVERTISE_PORT`  | Port to advertise         | 8081               | 9000               |
| `MCP_MESH_BIND_HOST`       | Interface to bind to      | 0.0.0.0            | 172.20.0.10        |
| `MCP_MESH_NETWORK_TIMEOUT` | Network operation timeout | 30s                | 60s                |
| `MCP_MESH_DNS_CACHE_TTL`   | DNS cache duration        | 60s                | 300s               |

## Examples

### Example 1: Multi-Region Networking

```yaml
# docker-compose.multi-region.yml
version: "3.8"

networks:
  us-east:
    driver: overlay
    attachable: true
    ipam:
      config:
        - subnet: 10.1.0.0/16

  us-west:
    driver: overlay
    attachable: true
    ipam:
      config:
        - subnet: 10.2.0.0/16

  global:
    driver: overlay
    attachable: true

services:
  # US East Region
  registry-east:
    image: mcp-mesh/registry:latest
    networks:
      - us-east
      - global
    environment:
      REGION: us-east
      PEER_REGISTRIES: registry-west.global

  agents-east:
    image: mcp-mesh/agent:0.2
    deploy:
      replicas: 5
    networks:
      - us-east
    environment:
      MCP_MESH_REGISTRY_URL: http://registry-east:8000
      REGION: us-east

  # US West Region
  registry-west:
    image: mcp-mesh/registry:latest
    networks:
      - us-west
      - global
    environment:
      REGION: us-west
      PEER_REGISTRIES: registry-east.global

  agents-west:
    image: mcp-mesh/agent:0.2
    deploy:
      replicas: 5
    networks:
      - us-west
    environment:
      MCP_MESH_REGISTRY_URL: http://registry-west:8000
      REGION: us-west
```

### Example 2: Service Mesh Integration

```yaml
# docker-compose.service-mesh.yml
version: "3.8"

services:
  # Envoy proxy sidecar for each agent
  weather-agent:
    image: mcp-mesh/agent:0.2
    networks:
      - mesh-net
    environment:
      MCP_MESH_REGISTRY_URL: http://localhost:9901/registry

  weather-proxy:
    image: envoyproxy/envoy:latest
    volumes:
      - ./envoy/weather-envoy.yaml:/etc/envoy/envoy.yaml
    network_mode: "service:weather-agent"
    command: ["-c", "/etc/envoy/envoy.yaml"]

  # Consul for service discovery
  consul:
    image: consul:latest
    networks:
      - mesh-net
    ports:
      - "8500:8500"
    command: agent -server -bootstrap-expect=1 -ui -client=0.0.0.0
```

## Best Practices

1. **Use Custom Networks**: Don't rely on default bridge network
2. **Implement Network Policies**: Restrict communication between zones
3. **Monitor Network Traffic**: Use tools like iftop or nethogs
4. **Plan IP Addressing**: Use consistent subnets across environments
5. **Document Network Topology**: Maintain network diagrams

## Common Pitfalls

### Pitfall 1: Container Name Resolution Fails

**Problem**: Agents can't resolve other container names

**Solution**: Ensure containers are on the same network:

```bash
# Check container networks
docker inspect weather-agent | jq '.[0].NetworkSettings.Networks'

# Connect to network if missing
docker network connect mcp-mesh-net weather-agent

# In compose, explicitly set networks
services:
  agent:
    networks:
      - mesh-net  # Must match other services
```

### Pitfall 2: Port Conflicts

**Problem**: Multiple agents trying to use same port

**Solution**: Use dynamic port allocation:

```yaml
services:
  agent-1:
    environment:
      SERVICE_PORT: 8081
    ports:
      - "8081:8081"

  agent-2:
    environment:
      SERVICE_PORT: 8082
    ports:
      - "8082:8082"
```

## Testing

### Network Connectivity Tests

```python
# tests/test_network_connectivity.py
import docker
import requests

def test_agent_connectivity():
    """Test agents can reach each other"""
    client = docker.from_env()

    # Get container IPs
    registry = client.containers.get('registry')
    registry_ip = registry.attrs['NetworkSettings']['Networks']['mesh-net']['IPAddress']

    # Test from agent container
    agent = client.containers.get('weather-agent')

    # Execute connectivity test inside container
    result = agent.exec_run(f'curl -s http://{registry_ip}:8000/health')
    assert result.exit_code == 0
    assert 'healthy' in result.output.decode()

def test_network_isolation():
    """Test network isolation works"""
    client = docker.from_env()

    # Agent in data network shouldn't be reachable from dmz
    dmz_agent = client.containers.get('api-gateway')

    # Try to reach data tier (should fail)
    result = dmz_agent.exec_run('curl -s --connect-timeout 5 http://database-agent:8081')
    assert result.exit_code != 0  # Should timeout/fail
```

### DNS Resolution Tests

```bash
#!/bin/bash
# test_dns_resolution.sh

echo "Testing DNS resolution in containers..."

# Test from each container
for container in registry weather-agent database-agent; do
  echo "Testing from $container:"

  # Test internal DNS
  docker exec $container nslookup registry
  docker exec $container ping -c 1 registry

  # Test external DNS
  docker exec $container nslookup google.com
done

# Test custom domains
docker exec weather-agent nslookup registry.mesh.local
```

## Monitoring and Debugging

### Network Debugging Tools

```yaml
# docker-compose.debug.yml
services:
  network-tools:
    image: nicolaka/netshoot
    networks:
      - mesh-net
    command: tail -f /dev/null
    cap_add:
      - NET_ADMIN
      - NET_RAW
```

Debug commands:

```bash
# Enter debug container
docker-compose exec network-tools bash

# Inside container:
# DNS debugging
nslookup registry
dig registry.mesh.local

# Network path testing
traceroute registry
mtr registry

# Port scanning
nmap -p 8000,8081 172.20.0.0/24

# Packet capture
tcpdump -i eth0 host registry

# Connection testing
nc -zv registry 8000
```

### Network Metrics

```bash
# Monitor network usage
docker stats --format "table {{.Container}}\t{{.NetIO}}"

# Check network interfaces
docker exec weather-agent ip addr

# View routing table
docker exec weather-agent ip route

# Network namespace debugging
docker inspect weather-agent | jq '.[0].NetworkSettings'
```

## 🔧 Troubleshooting

### Issue 1: Intermittent Connection Failures

**Symptoms**: Random "connection refused" errors

**Cause**: Docker's userland proxy issues

**Solution**:

```yaml
# Disable userland proxy
services:
  agent:
    ports:
      - target: 8081
        published: 8081
        protocol: tcp
        mode: host # Use host networking for port
```

### Issue 2: Slow DNS Resolution

**Symptoms**: Long delays before connections

**Cause**: DNS timeout/cache issues

**Solution**:

```yaml
services:
  agent:
    dns_options:
      - ndots:0 # Don't append search domains
      - timeout:1 # 1 second timeout
      - attempts:2 # 2 attempts max
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Docker Bridge Network**: Limited to single host
- **Overlay Networks**: Require Swarm mode or external orchestrator
- **MacVLAN**: Complex setup and limited platform support
- **IPv6**: Requires additional configuration

## 📝 TODO

- [ ] Add IPv6 networking examples
- [ ] Document CNI plugin integration
- [ ] Add network policy examples
- [ ] Create network topology visualizer
- [ ] Add eBPF monitoring examples

## Summary

You now understand Docker networking for MCP Mesh deployments:

Key takeaways:

- 🔑 Custom networks for agent isolation and organization
- 🔑 DNS-based service discovery within Docker
- 🔑 Network security through segmentation
- 🔑 Debugging tools for network issues

## Next Steps

Let's explore data persistence strategies for containerized agents.

Continue to [Persistent Storage](./05-storage.md) →

---

💡 **Tip**: Use `docker network prune` to clean up unused networks and avoid conflicts

📚 **Reference**: [Docker Networking Documentation](https://docs.docker.com/network/)

🧪 **Try It**: Create a three-tier network architecture with proper isolation between tiers

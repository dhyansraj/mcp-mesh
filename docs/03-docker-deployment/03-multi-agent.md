# Multi-Agent Deployment

> Deploy and manage complex networks of interdependent MCP Mesh agents with Docker

## Overview

Real-world MCP Mesh deployments often involve multiple agents working together - some providing core services, others consuming them, and many doing both. This guide covers deploying multi-agent systems, managing inter-agent dependencies, implementing service patterns, and ensuring reliable operation at scale.

We'll explore patterns for agent organization, dependency management, load balancing, and failure handling in multi-agent deployments.

## Key Concepts

- **Agent Topology**: Organizing agents into logical groups and tiers
- **Service Dependencies**: Managing complex dependency chains
- **Load Distribution**: Running multiple instances of the same agent
- **Failure Isolation**: Preventing cascading failures
- **Service Mesh Patterns**: Circuit breakers, retries, and timeouts

## Step-by-Step Guide

### Step 1: Design Your Agent Architecture

Define agent relationships and dependencies:

```yaml
# architecture.yml - Document your agent topology
agents:
  core_services:
    - name: auth-agent
      provides: ["authentication", "authorization"]
      depends_on: []

    - name: database-agent
      provides: ["data_storage", "data_query"]
      depends_on: ["auth-agent"]

  business_services:
    - name: user-agent
      provides: ["user_management"]
      depends_on: ["auth-agent", "database-agent"]

    - name: order-agent
      provides: ["order_processing"]
      depends_on: ["user-agent", "inventory-agent", "payment-agent"]

  support_services:
    - name: notification-agent
      provides: ["email", "sms", "push"]
      depends_on: ["auth-agent"]

    - name: analytics-agent
      provides: ["metrics", "reporting"]
      depends_on: ["database-agent"]
```

### Step 2: Implement Multi-Agent Docker Compose

Create a comprehensive deployment:

```yaml
# docker-compose.multi-agent.yml
version: '3.8'

x-common-agent: &common-agent
  image: mcp-mesh/agent:latest
  restart: unless-stopped
  environment:
    MCP_MESH_REGISTRY_URL: http://registry:8000
    MCP_MESH_LOG_LEVEL: ${LOG_LEVEL:-INFO}
  depends_on:
    registry:
      condition: service_healthy

services:
  # Infrastructure
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_MULTIPLE_DATABASES: mcp_mesh,auth_db,business_db
    volumes:
      - ./scripts/create-multiple-databases.sh:/docker-entrypoint-initdb.d/create-databases.sh
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  registry:
    image: mcp-mesh/registry:latest
    ports:
      - "8000:8000"
    environment:
      MCP_MESH_DB_TYPE: postgresql
      MCP_MESH_DB_HOST: postgres
      MCP_MESH_DB_NAME: mcp_mesh
    depends_on:
      postgres:
        condition: service_healthy

  # Core Services Layer
  auth-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/auth_agent.py"]
      DB_HOST: postgres
      DB_NAME: auth_db
      REDIS_HOST: redis
    deploy:
      replicas: 2

  database-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/database_agent.py"]
      DB_HOST: postgres
      DB_NAME: business_db
      CACHE_HOST: redis
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      auth-agent:
        condition: service_started

  # Business Services Layer
  user-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/user_agent.py"]
    depends_on:
      auth-agent:
        condition: service_started
      database-agent:
        condition: service_started
    deploy:
      replicas: 3
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3

  order-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/order_agent.py"]
      ORDER_PROCESSING_TIMEOUT: 30
    depends_on:
      user-agent:
        condition: service_started
      inventory-agent:
        condition: service_started
      payment-agent:
        condition: service_started

  inventory-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/inventory_agent.py"]
    depends_on:
      database-agent:
        condition: service_started

  payment-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/payment_agent.py"]
      PAYMENT_GATEWAY_URL: ${PAYMENT_GATEWAY_URL}
    secrets:
      - payment_api_key

  # Support Services Layer
  notification-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/notification_agent.py"]
      SMTP_HOST: ${SMTP_HOST}
      SMS_PROVIDER_URL: ${SMS_PROVIDER_URL}
    depends_on:
      auth-agent:
        condition: service_started

  analytics-agent:
    <<: *common-agent
    environment:
      <<: *common-agent.environment
    command: ["./bin/meshctl", "start", "examples/simple/analytics_agent.py"]
      BATCH_SIZE: 1000
      PROCESSING_INTERVAL: 60
    depends_on:
      database-agent:
        condition: service_started

  # Load Balancer
  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - user-agent
      - order-agent

volumes:
  postgres_data:
  redis_data:

secrets:
  payment_api_key:
    external: true

networks:
  default:
    name: mesh-network
    driver: bridge
```

### Step 3: Implement Agent Startup Orchestration

Create startup script for ordered initialization:

```bash
#!/bin/bash
# scripts/start-multi-agent.sh

echo "Starting MCP Mesh Multi-Agent System..."

# Start infrastructure
echo "Starting infrastructure services..."
docker-compose up -d postgres redis
sleep 10

# Start registry
echo "Starting registry..."
docker-compose up -d registry
until curl -s http://localhost:8000/health > /dev/null; do
  echo "Waiting for registry..."
  sleep 2
done

# Start core services
echo "Starting core services..."
docker-compose up -d auth-agent database-agent
sleep 5

# Start business services
echo "Starting business services..."
docker-compose up -d user-agent inventory-agent payment-agent
sleep 5

# Start dependent business services
echo "Starting dependent services..."
docker-compose up -d order-agent

# Start support services
echo "Starting support services..."
docker-compose up -d notification-agent analytics-agent

# Start load balancer
echo "Starting load balancer..."
docker-compose up -d nginx

echo "Multi-agent system started successfully!"
docker-compose ps
```

### Step 4: Implement Service Patterns

Add resilience patterns to agents:

```python
# agents/business/order_agent.py
import mesh
import asyncio
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = None
        self.is_open = False

@mesh.agent(name="order-processor")
class OrderProcessor:
    pass

@mesh.tool(
    capability="order_processing",
    dependencies=[
        "user_get",
        "inventory_check_stock",
        "inventory_reserve_items",
        "payment_process",
        "notification_send_email"
    ]
)
async def process_order(
    order_data: dict,
    user_get=None,
    inventory_check_stock=None,
    inventory_reserve_items=None,
    payment_process=None,
    notification_send_email=None
):
    """Process order with circuit breaker and retry logic"""

    order_id = order_data.get("order_id")
    logger.info(f"Processing order {order_id}")

    try:
        # Step 1: Validate user
        user = await retry_with_backoff(
            lambda: user_get(order_data["user_id"]),
            max_retries=3,
            service_name="user_get"
        )

        if not user:
            raise ValueError("User not found")

        # Step 2: Check inventory (with circuit breaker)
        if not await check_with_circuit_breaker(
            lambda: inventory_check_stock(order_data["items"]),
            "inventory_check_stock"
        ):
            return {"error": "Insufficient stock"}

        # Step 3: Reserve items
        reservation = await inventory_reserve_items(
            order_data["items"],
            timeout=30  # 30 second timeout
        )

        try:
            # Step 4: Process payment
            payment_result = await payment_process({
                "user_id": user["id"],
                "amount": order_data["total"],
                "order_id": order_id
            })

            if payment_result["status"] != "success":
                raise Exception("Payment failed")

            # Step 5: Send confirmation (non-critical)
            try:
                await notification_send_email({
                    "to": user["email"],
                    "subject": f"Order {order_id} Confirmed",
                    "body": "Your order has been processed successfully."
                })
            except Exception as e:
                logger.warning(f"Failed to send email: {e}")
                # Continue - email failure shouldn't fail the order

            return {
                "status": "completed",
                "order_id": order_id,
                "payment_id": payment_result["payment_id"]
            }

        except Exception as e:
            # Rollback inventory reservation
            if 'inventory_release_reservation' in locals():
                await inventory_release_reservation(reservation["id"])
            raise

    except Exception as e:
        logger.error(f"Order {order_id} failed: {e}")
        return {
            "status": "failed",
            "order_id": order_id,
            "error": str(e)
        }

async def retry_with_backoff(func, max_retries=3, service_name=""):
    """Retry with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait_time = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Retry {attempt + 1} for {service_name} after {wait_time}s")
            await asyncio.sleep(wait_time)
```

## Configuration Options

| Option                      | Description                | Default | Example |
| --------------------------- | -------------------------- | ------- | ------- |
| `AGENT_STARTUP_DELAY`       | Delay between agent starts | 5s      | 10s     |
| `MAX_REPLICAS`              | Maximum agent replicas     | 5       | 10      |
| `HEALTH_CHECK_INTERVAL`     | Health check frequency     | 30s     | 60s     |
| `DEPENDENCY_TIMEOUT`        | Timeout for dependencies   | 30s     | 60s     |
| `CIRCUIT_BREAKER_THRESHOLD` | Failures before open       | 5       | 10      |

## Examples

### Example 1: Microservices Pattern

```yaml
# docker-compose.microservices.yml
version: "3.8"

services:
  # API Gateway
  api-gateway:
    image: mcp-mesh/agent:latest
    command: ["./bin/meshctl", "start", "examples/simple/api_gateway.py"]
    environment:
      RATE_LIMIT: 1000
    ports:
      - "8000:8000"
    deploy:
      replicas: 2

  # Microservices
  product-service:
    image: mcp-mesh/agent:latest
    command: ["./bin/meshctl", "start", "examples/simple/product_service.py"]
    deploy:
      replicas: 3
      labels:
        - "traefik.enable=true"
        - "traefik.http.services.products.loadbalancer.server.port=8080"

  cart-service:
    image: mcp-mesh/agent:latest
    command: ["./bin/meshctl", "start", "examples/simple/cart_service.py"]
    environment:
      REDIS_HOST: redis
    deploy:
      replicas: 2

  recommendation-service:
    image: mcp-mesh/agent:latest
    command:
      ["./bin/meshctl", "start", "examples/simple/recommendation_service.py"]
    environment:
      ML_MODEL_PATH: /models/recommendation.pkl
    volumes:
      - ./models:/models:ro
    deploy:
      resources:
        limits:
          memory: 2G
```

### Example 2: Event-Driven Architecture

```yaml
# docker-compose.event-driven.yml
version: "3.8"

services:
  # Event Bus
  rabbitmq:
    image: rabbitmq:3-management-alpine
    ports:
      - "5672:5672"
      - "15672:15672"
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq

  # Event Producers
  order-creator:
    image: mcp-mesh/agent:latest
    command: ["./bin/meshctl", "start", "examples/simple/order_creator.py"]
    environment:
      RABBITMQ_URL: amqp://rabbitmq:5672
      PUBLISH_TO: orders.created

  # Event Processors
  order-processor:
    image: mcp-mesh/agent:latest
    command: ["./bin/meshctl", "start", "examples/simple/order_processor.py"]
    environment:
      RABBITMQ_URL: amqp://rabbitmq:5672
      SUBSCRIBE_TO: orders.created
      PUBLISH_TO: orders.processed
    deploy:
      replicas: 5

  # Event Consumers
  email-sender:
    image: mcp-mesh/agent:latest
    command: ["./bin/meshctl", "start", "examples/simple/email_sender.py"]
    environment:
      RABBITMQ_URL: amqp://rabbitmq:5672
      SUBSCRIBE_TO: orders.processed,orders.shipped

volumes:
  rabbitmq_data:
```

## Best Practices

1. **Layer Your Services**: Core → Business → Support services
2. **Implement Health Checks**: Every agent should have health endpoints
3. **Use Graceful Shutdowns**: Handle SIGTERM properly
4. **Monitor Dependencies**: Track and alert on dependency failures
5. **Plan for Failure**: Design for partial system availability

## Common Pitfalls

### Pitfall 1: Circular Dependencies

**Problem**: Agent A depends on B, B depends on A

**Solution**: Refactor to break circular dependencies:

```python
# Bad: Circular dependency
@mesh.tool(dependencies=["service_b_func"])
def service_a_func(service_b_func=None):
    return service_b_func()

# Good: Extract shared functionality
@mesh.tool(dependencies=["shared_service_func"])
def service_a_func(shared_service_func=None):
    return shared_service_func()
```

### Pitfall 2: Cascading Failures

**Problem**: One service failure brings down entire system

**Solution**: Implement circuit breakers and fallbacks:

```python
@mesh.tool(
    capability="resilient_service",
    dependencies=["critical_service_func"]
)
def resilient_service(critical_service_func=None):
    if critical_service_func:
        try:
            return critical_service_func()
        except Exception:
            pass
    return {"status": "degraded", "data": get_cached_data()}
```

## Testing

### Load Testing Multi-Agent Systems

```python
# tests/load_test_multi_agent.py
import asyncio
import aiohttp
import time

async def test_order_processing_load():
    """Test system under load"""
    async with aiohttp.ClientSession() as session:
        tasks = []

        # Create 1000 concurrent orders
        for i in range(1000):
            order = {
                "order_id": f"TEST-{i}",
                "user_id": f"user-{i % 100}",
                "items": [{"sku": "ITEM-1", "quantity": 1}],
                "total": 99.99
            }

            task = session.post(
                "http://localhost:8000/orders",
                json=order
            )
            tasks.append(task)

        start = time.time()
        responses = await asyncio.gather(*tasks)
        duration = time.time() - start

        success_count = sum(1 for r in responses if r.status == 200)

        print(f"Processed {success_count}/1000 orders in {duration:.2f}s")
        print(f"Throughput: {success_count/duration:.2f} orders/second")
```

### Chaos Testing

```bash
#!/bin/bash
# chaos_test.sh - Test system resilience

echo "Starting chaos test..."

# Kill random agent
AGENTS=(user-agent order-agent inventory-agent)
VICTIM=${AGENTS[$RANDOM % ${#AGENTS[@]}]}
echo "Killing $VICTIM..."
docker-compose kill $VICTIM

# Wait and check system health
sleep 10
curl -s http://localhost:8000/health

# Restart agent
docker-compose up -d $VICTIM

# Test gradual recovery
for i in {1..10}; do
  echo "Recovery check $i..."
  curl -s http://localhost:8000/orders/test | jq .
  sleep 5
done
```

## Monitoring and Debugging

### Multi-Agent Monitoring Stack

```yaml
# docker-compose.monitoring.yml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana_data:/var/lib/grafana
      - ./observability/grafana/dashboards:/etc/grafana/provisioning/dashboards
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"
      - "14268:14268"
    environment:
      COLLECTOR_ZIPKIN_HOST_PORT: :9411

volumes:
  prometheus_data:
  grafana_data:
```

### Debug Commands

```bash
# View agent dependencies
docker-compose exec registry curl http://localhost:8000/agents | jq

# Check agent health across all replicas
for i in {1..3}; do
  docker-compose exec --index=$i user-agent curl http://localhost:8888/health
done

# Trace request flow
docker-compose logs -f --tail=0 | grep "order-123"
```

## 🔧 Troubleshooting

### Issue 1: Agents Can't Find Dependencies

**Symptoms**: "Dependency not found" errors

**Cause**: Race condition or network issues

**Solution**:

```yaml
# Add retry logic to agents
environment:
  MCP_MESH_RETRY_ATTEMPTS: 10
  MCP_MESH_RETRY_DELAY: 5
  MCP_MESH_DISCOVERY_TIMEOUT: 30
```

### Issue 2: Memory/Resource Exhaustion

**Symptoms**: Containers getting OOMKilled

**Cause**: No resource limits set

**Solution**:

```yaml
deploy:
  resources:
    limits:
      memory: 512M
      cpus: "0.5"
    reservations:
      memory: 256M
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Docker Compose Scaling**: Limited compared to Kubernetes
- **Service Discovery**: Basic compared to service mesh solutions
- **State Management**: Challenging for stateful agents
- **Network Latency**: Container networking adds overhead

## 📝 TODO

- [ ] Add service mesh integration examples
- [ ] Create agent dependency visualizer
- [ ] Add canary deployment patterns
- [ ] Document state management strategies
- [ ] Add distributed tracing setup

## Summary

You can now deploy complex multi-agent MCP Mesh systems with:

Key takeaways:

- 🔑 Layered architecture for agent organization
- 🔑 Resilience patterns for production reliability
- 🔑 Load distribution and scaling strategies
- 🔑 Comprehensive monitoring and debugging

## Next Steps

Let's explore networking and service discovery in containerized environments.

Continue to [Networking and Service Discovery](./04-networking.md) →

---

💡 **Tip**: Use `docker-compose logs -f --tail=100 | grep ERROR` to monitor all agents for errors in real-time

📚 **Reference**: [Microservices Patterns](https://microservices.io/patterns/)

🧪 **Try It**: Deploy a 10-agent system with complex dependencies and test failure scenarios

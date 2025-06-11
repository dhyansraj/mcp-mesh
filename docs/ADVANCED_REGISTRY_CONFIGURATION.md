# Advanced Registry Configuration and Features

This document provides comprehensive documentation for MCP Mesh's advanced registry configuration and features.

## Table of Contents

1. [Configuration Overview](#configuration-overview)
2. [Configuration Sources](#configuration-sources)
3. [Configuration Schema](#configuration-schema)
4. [Advanced Features](#advanced-features)
5. [Security Configuration](#security-configuration)
6. [Performance Tuning](#performance-tuning)
7. [Monitoring and Observability](#monitoring-and-observability)
8. [Examples](#examples)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)

## Configuration Overview

MCP Mesh provides a comprehensive configuration system that supports:

- **Hierarchical Configuration**: Multiple configuration sources with priority ordering
- **Type-Safe Configuration**: Pydantic-based configuration models with validation
- **Environment-Specific Settings**: Support for development, testing, and production environments
- **Hot Reloading**: Dynamic configuration updates without service restart
- **Validation and Error Handling**: Comprehensive configuration validation with clear error messages

### Configuration Architecture

```python
from mcp_mesh_types import RegistryConfig, ServerConfig, DatabaseConfig

# Load configuration from multiple sources
config = RegistryConfig(
    mode=RegistryMode.STANDALONE,
    server=ServerConfig(host="0.0.0.0", port=8000),
    database=DatabaseConfig(database_path="registry.db"),
    security=SecurityConfig(mode=SecurityMode.JWT),
    # ... additional configuration
)
```

## Configuration Sources

MCP Mesh supports multiple configuration sources with the following priority order (highest to lowest):

1. **Command Line Arguments**
2. **Environment Variables**
3. **Configuration Files** (YAML, JSON)
4. **Default Values**

### Environment Variables

All configuration options can be set via environment variables with the `MCP_MESH_` prefix:

```bash
# Server configuration
export MCP_MESH_HOST=0.0.0.0
export MCP_MESH_PORT=8000
export MCP_MESH_WORKERS=4

# Database configuration
export MCP_MESH_DB_PATH=/data/registry.db
export MCP_MESH_DB_TIMEOUT=60

# Security configuration
export MCP_MESH_SECURITY_MODE=jwt
export MCP_MESH_JWT_SECRET=your-secret-key

# Feature flags
export MCP_MESH_DEBUG=true
export MCP_MESH_ENVIRONMENT=production
```

### Configuration Files

#### YAML Configuration

```yaml
# config.yaml
mode: standalone
environment: production
debug: false

server:
  host: 0.0.0.0
  port: 8000
  workers: 4
  max_connections: 1000
  timeout: 30
  enable_ssl: true
  ssl_cert_path: /etc/ssl/certs/registry.pem
  ssl_key_path: /etc/ssl/private/registry.key
  enable_cors: true
  cors_origins:
    - "https://dashboard.example.com"
    - "https://api.example.com"
  rate_limit_enabled: true
  rate_limit_requests: 1000
  rate_limit_window: 3600

database:
  database_type: postgresql
  connection_string: postgresql://user:pass@localhost:5432/registry
  max_connections: 20
  pool_size: 10
  connection_timeout: 30
  enable_encryption: true
  backup_enabled: true
  backup_interval: 3600

security:
  mode: jwt
  jwt_secret: your-jwt-secret-key
  jwt_expiration: 3600
  allowed_hosts:
    - "*.example.com"
    - "localhost"
  enable_audit_log: true
  audit_log_path: /var/log/mcp-mesh-audit.log

discovery:
  enable_caching: true
  cache_ttl: 300
  registry_timeout: 30
  max_retries: 3
  retry_delay: 1.0
  health_check_enabled: true
  health_check_interval: 60
  health_check_timeout: 10
  agent_registration_ttl: 3600

monitoring:
  enable_metrics: true
  metrics_port: 9090
  enable_tracing: true
  jaeger_endpoint: http://jaeger:14268
  log_level: INFO
  log_format: json
  log_file_path: /var/log/mcp-mesh.log
  enable_performance_metrics: true
  metrics_retention_days: 30

performance:
  max_concurrent_requests: 500
  request_timeout: 30
  keep_alive_timeout: 5
  max_request_size: 10485760 # 10MB
  enable_compression: true
  compression_level: 6
  cache_enabled: true
  cache_size: 10000
  cache_ttl: 300
  background_task_workers: 4

feature_flags:
  enable_experimental_features: false
  enable_legacy_compatibility: true
  enable_advanced_metrics: true
```

#### JSON Configuration

```json
{
  "mode": "clustered",
  "environment": "production",
  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "workers": 8,
    "enable_ssl": true
  },
  "database": {
    "database_type": "postgresql",
    "connection_string": "postgresql://user:pass@db:5432/registry",
    "max_connections": 50
  },
  "security": {
    "mode": "mutual_tls",
    "tls_ca_cert": "/etc/ssl/ca.pem",
    "require_client_cert": true
  }
}
```

## Configuration Schema

### RegistryConfig

The root configuration object containing all registry settings.

```python
class RegistryConfig:
    mode: RegistryMode = RegistryMode.STANDALONE
    server: ServerConfig
    database: DatabaseConfig
    security: SecurityConfig
    discovery: ServiceDiscoveryConfig
    monitoring: MonitoringConfig
    performance: PerformanceConfig
    environment: str = "development"
    debug: bool = False
    feature_flags: Dict[str, bool] = {}
```

### ServerConfig

HTTP server configuration settings.

```python
class ServerConfig:
    host: str = "localhost"
    port: int = 8000
    workers: int = 1
    max_connections: int = 100
    timeout: int = 30
    enable_ssl: bool = False
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    enable_cors: bool = True
    cors_origins: List[str] = ["*"]
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
```

### DatabaseConfig

Database connection and performance settings.

```python
class DatabaseConfig:
    database_type: DatabaseType = DatabaseType.SQLITE
    database_path: str = "mcp_mesh_registry.db"
    connection_string: Optional[str] = None
    connection_timeout: int = 30
    busy_timeout: int = 5000
    max_connections: int = 10
    pool_size: int = 5
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size: int = 10000
    enable_foreign_keys: bool = True
    enable_encryption: bool = False
    backup_enabled: bool = False
    backup_interval: int = 3600
```

### SecurityConfig

Security and authentication settings.

```python
class SecurityConfig:
    mode: SecurityMode = SecurityMode.NONE
    api_keys: List[str] = []
    jwt_secret: Optional[str] = None
    jwt_expiration: int = 3600
    tls_ca_cert: Optional[str] = None
    require_client_cert: bool = False
    allowed_hosts: List[str] = []
    enable_audit_log: bool = False
    audit_log_path: Optional[str] = None
```

## Advanced Features

### 1. Service Discovery Configuration

```python
class ServiceDiscoveryConfig:
    enable_caching: bool = True
    cache_ttl: int = 300
    registry_timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    health_check_enabled: bool = True
    health_check_interval: int = 60
    health_check_timeout: int = 10
    agent_registration_ttl: int = 3600
    auto_refresh_enabled: bool = True
    refresh_interval: int = 300
```

**Features:**

- **Intelligent Caching**: Cache service discovery results to reduce registry load
- **Health Monitoring**: Automatic health checks for registered agents
- **Retry Logic**: Configurable retry policies for failed requests
- **TTL Management**: Automatic cleanup of stale registrations

### 2. Agent Selection Algorithms

Configure advanced agent selection strategies:

```python
# Weighted selection with custom criteria
selection_weights = SelectionWeights(
    capability_match=0.4,
    performance=0.3,
    availability=0.2,
    proximity=0.1
)

# Round-robin load balancing
selection_manager.algorithm = "round_robin"

# Load-based selection
selection_manager.algorithm = "load_balanced"
```

### 3. Lifecycle Management

```python
class LifecycleConfig:
    graceful_shutdown_timeout: int = 30
    health_check_failures_threshold: int = 3
    auto_restart_enabled: bool = False
    drain_timeout: int = 60
```

### 4. Versioning and Deployment

```python
# Canary deployment configuration
canary_config = {
    "traffic_split": {"v1.0.0": 90, "v1.1.0": 10},
    "success_criteria": {
        "error_rate_threshold": 0.01,
        "latency_p99_threshold": 1000
    },
    "rollback_triggers": ["high_error_rate", "health_check_failure"]
}
```

## Security Configuration

### Authentication Modes

#### 1. API Key Authentication

```yaml
security:
  mode: api_key
  api_keys:
    - "prod-key-1"
    - "prod-key-2"
```

```python
# Usage
headers = {"X-API-Key": "prod-key-1"}
response = requests.get("http://registry:8000/agents", headers=headers)
```

#### 2. JWT Authentication

```yaml
security:
  mode: jwt
  jwt_secret: "your-secret-key"
  jwt_expiration: 3600
```

```python
# Generate JWT token
import jwt
token = jwt.encode({"user": "client", "exp": time.time() + 3600}, "your-secret-key")

# Use token
headers = {"Authorization": f"Bearer {token}"}
response = requests.get("http://registry:8000/agents", headers=headers)
```

#### 3. Mutual TLS

```yaml
security:
  mode: mutual_tls
  tls_ca_cert: /etc/ssl/ca.pem
  require_client_cert: true
```

### Audit Logging

```yaml
security:
  enable_audit_log: true
  audit_log_path: /var/log/mcp-mesh-audit.log
```

Audit log format:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "event": "agent_registration",
  "user": "client-1",
  "agent_id": "file-agent-001",
  "source_ip": "192.168.1.100",
  "success": true
}
```

## Performance Tuning

### High-Performance Configuration

```yaml
server:
  workers: 8
  max_connections: 1000
  timeout: 60

database:
  max_connections: 50
  pool_size: 20
  cache_size: 50000

performance:
  max_concurrent_requests: 1000
  enable_compression: true
  cache_enabled: true
  cache_size: 50000
  background_task_workers: 8
```

### Database Optimization

```yaml
database:
  journal_mode: WAL
  synchronous: NORMAL
  cache_size: 50000
  busy_timeout: 10000
  enable_foreign_keys: true
```

For PostgreSQL:

```yaml
database:
  database_type: postgresql
  connection_string: postgresql://user:pass@localhost:5432/registry?pool_size=20&max_overflow=30
  max_connections: 50
```

## Monitoring and Observability

### Metrics Configuration

```yaml
monitoring:
  enable_metrics: true
  metrics_port: 9090
  enable_performance_metrics: true
  metrics_retention_days: 30
```

**Available Metrics:**

- Request rate and latency
- Agent registration/deregistration counts
- Health check success/failure rates
- Cache hit/miss ratios
- Database connection pool usage

### Distributed Tracing

```yaml
monitoring:
  enable_tracing: true
  jaeger_endpoint: http://jaeger:14268
```

### Logging Configuration

```yaml
monitoring:
  log_level: INFO
  log_format: json
  log_file_path: /var/log/mcp-mesh.log
```

Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

## Examples

### Development Configuration

```yaml
# dev-config.yaml
mode: standalone
environment: development
debug: true

server:
  host: localhost
  port: 8000
  workers: 1

database:
  database_path: dev_registry.db

security:
  mode: none

monitoring:
  log_level: DEBUG
  enable_metrics: false
```

### Production Configuration

```yaml
# prod-config.yaml
mode: clustered
environment: production
debug: false

server:
  host: 0.0.0.0
  port: 443
  workers: 8
  enable_ssl: true
  ssl_cert_path: /etc/ssl/certs/registry.pem
  ssl_key_path: /etc/ssl/private/registry.key

database:
  database_type: postgresql
  connection_string: postgresql://user:pass@db:5432/registry
  max_connections: 50
  enable_encryption: true
  backup_enabled: true

security:
  mode: jwt
  jwt_secret: ${JWT_SECRET}
  enable_audit_log: true

monitoring:
  enable_metrics: true
  enable_tracing: true
  log_level: INFO
  log_format: json
```

### Docker Compose Configuration

```yaml
# docker-compose.yml
version: "3.8"
services:
  registry:
    image: mcp-mesh/registry:latest
    ports:
      - "8000:8000"
      - "9090:9090"
    environment:
      - MCP_MESH_HOST=0.0.0.0
      - MCP_MESH_PORT=8000
      - MCP_MESH_DB_PATH=/data/registry.db
      - MCP_MESH_SECURITY_MODE=api_key
      - MCP_MESH_API_KEYS=prod-key-1,prod-key-2
    volumes:
      - registry_data:/data
      - ./config.yaml:/etc/mcp-mesh/config.yaml
    command: ["--config", "/etc/mcp-mesh/config.yaml"]

volumes:
  registry_data:
```

## Best Practices

### 1. Security Best Practices

- **Use strong authentication** in production environments
- **Enable TLS/SSL** for all external communications
- **Rotate API keys** regularly
- **Enable audit logging** for compliance and debugging
- **Use environment variables** for sensitive configuration

### 2. Performance Best Practices

- **Tune worker count** based on CPU cores (typically 2x cores)
- **Configure connection pooling** for database connections
- **Enable caching** for frequently accessed data
- **Use compression** for large responses
- **Monitor and optimize** database query performance

### 3. Operational Best Practices

- **Use configuration files** for complex setups
- **Implement health checks** for all critical components
- **Enable monitoring and metrics** collection
- **Set up proper logging** with appropriate levels
- **Test configuration changes** in non-production environments

### 4. Scalability Best Practices

- **Use clustered mode** for high availability
- **Implement load balancing** across multiple instances
- **Configure auto-scaling** based on metrics
- **Use external databases** (PostgreSQL) for production
- **Implement circuit breakers** for fault tolerance

## Troubleshooting

### Common Configuration Issues

#### 1. Port Already in Use

```
Error: Address already in use: 0.0.0.0:8000
```

**Solution:**

```yaml
server:
  port: 8080 # Use different port
```

#### 2. Database Connection Failed

```
Error: Unable to connect to database: connection timeout
```

**Solution:**

```yaml
database:
  connection_timeout: 60 # Increase timeout
  max_connections: 5 # Reduce connections
```

#### 3. SSL Certificate Issues

```
Error: SSL certificate not found: /path/to/cert.pem
```

**Solution:**

```yaml
server:
  enable_ssl: false # Disable SSL temporarily
  # OR fix certificate path
  ssl_cert_path: /correct/path/to/cert.pem
```

#### 4. Invalid Configuration Format

```
Error: Invalid configuration: 'mode' must be one of ['standalone', 'clustered', 'federated']
```

**Solution:**

```yaml
mode: standalone # Use valid enum value
```

### Configuration Validation

Use the built-in validation to check configuration:

```python
from mcp_mesh.shared.configuration import ConfigurationManager

manager = ConfigurationManager()
config = manager.load_from_file("config.yaml")

if manager.validate_config():
    print("Configuration is valid")
else:
    print("Configuration validation failed")
```

### Debug Mode

Enable debug mode for detailed logging:

```yaml
debug: true
monitoring:
  log_level: DEBUG
```

### Health Check Endpoints

- **Registry Health**: `GET /health`
- **Metrics**: `GET /metrics` (if monitoring enabled)
- **Configuration**: `GET /config` (debug mode only)

This comprehensive configuration system provides the flexibility and power needed for production MCP Mesh deployments while maintaining simplicity for development use cases.

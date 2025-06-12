# Maintenance and Operations Documentation

This document provides comprehensive guidance for maintaining and operating the MCP Mesh SDK in production environments, including deployment, monitoring, troubleshooting, and ongoing maintenance procedures.

## Table of Contents

1. [Build and Deployment](#build-and-deployment)
2. [Environment Configuration](#environment-configuration)
3. [Monitoring and Observability](#monitoring-and-observability)
4. [Health Checks and Diagnostics](#health-checks-and-diagnostics)
5. [Performance Monitoring](#performance-monitoring)
6. [Security Operations](#security-operations)
7. [Troubleshooting Guide](#troubleshooting-guide)
8. [Backup and Recovery](#backup-and-recovery)
9. [Update and Upgrade Procedures](#update-and-upgrade-procedures)
10. [Incident Response](#incident-response)

## Build and Deployment

### Build Process

#### Local Build

```bash
# Install build dependencies
pip install build twine

# Build package
python -m build

# Verify build
twine check dist/*

# Local installation
pip install dist/mcp_mesh_sdk-*.whl
```

#### Automated CI/CD Build

The project uses GitHub Actions for automated building:

```yaml
# .github/workflows/build.yml
name: Build and Test

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.10, 3.11, 3.12]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt

      - name: Run linting
        run: |
          black --check src/ tests/
          isort --check-only src/ tests/
          ruff check src/ tests/
          mypy src/

      - name: Run tests
        run: |
          pytest tests/unit/ --cov=mcp_mesh_sdk
          pytest tests/integration/

      - name: Build package
        run: python -m build

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### Deployment Strategies

#### PyPI Deployment

```bash
# Production release
python -m twine upload dist/*

# Test PyPI release
python -m twine upload --repository testpypi dist/*
```

#### Container Deployment

```dockerfile
# Dockerfile for containerized deployment
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy application code
COPY src/ ./src/
COPY setup.py pyproject.toml ./
RUN pip install -e .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
USER app

# Set environment variables
ENV PYTHONPATH=/app/src
ENV MCP_MESH_LOG_LEVEL=INFO

# Expose port for health checks
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import mcp_mesh_sdk; print('OK')" || exit 1

# Start application
CMD ["python", "-m", "mcp_mesh_sdk.server"]
```

#### Kubernetes Deployment

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-mesh-sdk
  labels:
    app: mcp-mesh-sdk
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcp-mesh-sdk
  template:
    metadata:
      labels:
        app: mcp-mesh-sdk
    spec:
      containers:
        - name: mcp-mesh-sdk
          image: mcp-mesh-sdk:latest
          ports:
            - containerPort: 8080
          env:
            - name: MESH_REGISTRY_URL
              value: "http://mesh-registry:8080"
            - name: LOG_LEVEL
              value: "INFO"
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-mesh-sdk
spec:
  selector:
    app: mcp-mesh-sdk
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
```

## Environment Configuration

### Production Configuration

```python
# config/production.py
import os
from typing import Dict, Any

PRODUCTION_CONFIG: Dict[str, Any] = {
    # Service Mesh Configuration
    "mesh_registry_url": os.getenv("MESH_REGISTRY_URL", "http://registry:8080"),
    "agent_name": os.getenv("AGENT_NAME", "mcp-mesh-agent"),
    "health_interval": int(os.getenv("HEALTH_INTERVAL", "30")),
    "fallback_mode": os.getenv("FALLBACK_MODE", "false").lower() == "true",

    # Security Configuration
    "security_context": os.getenv("SECURITY_CONTEXT", "production"),
    "enable_audit_logging": True,
    "audit_log_level": "INFO",

    # Performance Configuration
    "enable_caching": True,
    "cache_ttl_seconds": int(os.getenv("CACHE_TTL", "300")),
    "max_concurrent_operations": int(os.getenv("MAX_CONCURRENT_OPS", "100")),
    "request_timeout": int(os.getenv("REQUEST_TIMEOUT", "30")),

    # File Operations Configuration
    "base_directory": os.getenv("BASE_DIRECTORY"),
    "max_file_size": int(os.getenv("MAX_FILE_SIZE", str(10 * 1024 * 1024))),
    "allowed_extensions": set(os.getenv("ALLOWED_EXTENSIONS", ".txt,.json,.yaml").split(",")),

    # Logging Configuration
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    "log_format": "json",
    "enable_metrics": True,

    # Retry Configuration
    "default_retry_attempts": int(os.getenv("RETRY_ATTEMPTS", "3")),
    "retry_initial_delay_ms": int(os.getenv("RETRY_INITIAL_DELAY", "1000")),
    "retry_max_delay_ms": int(os.getenv("RETRY_MAX_DELAY", "30000")),
    "retry_backoff_multiplier": float(os.getenv("RETRY_BACKOFF", "2.0")),
}
```

### Environment Variables Reference

| Variable             | Description                        | Default                 | Required |
| -------------------- | ---------------------------------- | ----------------------- | -------- |
| `MESH_REGISTRY_URL`  | Service mesh registry URL          | `http://localhost:8080` | No       |
| `AGENT_NAME`         | Agent identifier                   | `auto-generated`        | No       |
| `HEALTH_INTERVAL`    | Health check interval (seconds)    | `30`                    | No       |
| `FALLBACK_MODE`      | Enable fallback mode               | `true`                  | No       |
| `SECURITY_CONTEXT`   | Security context identifier        | `default`               | No       |
| `BASE_DIRECTORY`     | Base directory for file operations | `None`                  | No       |
| `MAX_FILE_SIZE`      | Maximum file size (bytes)          | `10485760`              | No       |
| `LOG_LEVEL`          | Logging level                      | `INFO`                  | No       |
| `CACHE_TTL`          | Cache TTL (seconds)                | `300`                   | No       |
| `MAX_CONCURRENT_OPS` | Max concurrent operations          | `100`                   | No       |

### Secrets Management

#### Using Environment Variables

```bash
# .env file for development (DO NOT commit to version control)
MESH_REGISTRY_URL=http://localhost:8080
AGENT_NAME=dev-agent
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://user:pass@localhost/db
```

#### Using Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mcp-mesh-secrets
type: Opaque
data:
  secret-key: <base64-encoded-secret>
  database-url: <base64-encoded-db-url>
---
apiVersion: apps/v1
kind: Deployment
# ... deployment spec ...
        env:
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: mcp-mesh-secrets
              key: secret-key
```

## Monitoring and Observability

### Logging Configuration

```python
# logging_config.py
import logging
import json
from datetime import datetime
from typing import Dict, Any

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        # Add extra fields
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        if hasattr(record, 'correlation_id'):
            log_entry['correlation_id'] = record.correlation_id
        if hasattr(record, 'operation'):
            log_entry['operation'] = record.operation

        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry)

def setup_logging(log_level: str = "INFO", use_json: bool = True) -> None:
    """Setup logging configuration."""

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler()

    if use_json:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Configure specific loggers
    logging.getLogger("mcp_mesh_sdk").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
```

### Metrics Collection

```python
# metrics.py
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict, deque
import threading

@dataclass
class MetricSample:
    """Individual metric sample."""
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)

class MetricsCollector:
    """Collect and expose application metrics."""

    def __init__(self, max_samples: int = 1000):
        self.max_samples = max_samples
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_samples))
        self._lock = threading.Lock()

    def increment_counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] += value

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value

    def observe_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Add observation to histogram."""
        with self._lock:
            key = self._make_key(name, labels)
            self._histograms[key].append(MetricSample(
                value=value,
                timestamp=time.time(),
                labels=labels or {}
            ))

    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: [{"value": s.value, "timestamp": s.timestamp, "labels": s.labels}
                           for s in samples]
                    for name, samples in self._histograms.items()
                }
            }

    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """Create metric key with labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

# Global metrics instance
metrics = MetricsCollector()

# Usage in code
def track_operation_metrics(operation: str):
    """Decorator to track operation metrics."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            metrics.increment_counter("operations_total", labels={"operation": operation})

            try:
                result = await func(*args, **kwargs)
                metrics.increment_counter("operations_success", labels={"operation": operation})
                return result
            except Exception as e:
                metrics.increment_counter("operations_error", labels={
                    "operation": operation,
                    "error_type": type(e).__name__
                })
                raise
            finally:
                duration = time.time() - start_time
                metrics.observe_histogram("operation_duration_seconds", duration,
                                        labels={"operation": operation})

        return wrapper
    return decorator
```

### Health Check Endpoints

```python
# health.py
from fastapi import FastAPI, Response
from typing import Dict, Any
import asyncio
from datetime import datetime

from mcp_mesh_sdk.tools.file_operations import FileOperations
from mcp_mesh_sdk.shared.types import HealthStatusType

app = FastAPI()

# Global health check components
file_ops = FileOperations()

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0"
    }

@app.get("/health/detailed")
async def detailed_health_check() -> Dict[str, Any]:
    """Detailed health check with component status."""
    health_status = await file_ops.health_check()

    return {
        "status": health_status.status.value,
        "timestamp": health_status.timestamp.isoformat(),
        "checks": health_status.checks,
        "errors": health_status.errors,
        "uptime_seconds": health_status.uptime_seconds,
        "metadata": health_status.metadata
    }

@app.get("/ready")
async def readiness_check(response: Response) -> Dict[str, Any]:
    """Readiness check for load balancer."""
    try:
        # Check critical dependencies
        health_status = await file_ops.health_check()

        if health_status.status == HealthStatusType.HEALTHY:
            return {"status": "ready"}
        else:
            response.status_code = 503
            return {
                "status": "not_ready",
                "reason": "health_check_failed",
                "errors": health_status.errors
            }
    except Exception as e:
        response.status_code = 503
        return {
            "status": "not_ready",
            "reason": "health_check_error",
            "error": str(e)
        }

@app.get("/metrics")
async def metrics_endpoint() -> Dict[str, Any]:
    """Expose metrics for monitoring."""
    from .metrics import metrics
    return metrics.get_metrics()
```

## Health Checks and Diagnostics

### System Health Monitoring

```python
# diagnostics.py
import os
import psutil
import asyncio
from typing import Dict, Any, List
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SystemHealth:
    """System health information."""
    cpu_percent: float
    memory_percent: float
    disk_usage_percent: float
    load_average: List[float]
    available_memory_mb: float
    free_disk_space_gb: float

class SystemDiagnostics:
    """System diagnostics and health checking."""

    def __init__(self):
        self.critical_paths = ["/tmp", "/var/log"]
        self.memory_threshold_percent = 90
        self.disk_threshold_percent = 85
        self.cpu_threshold_percent = 80

    async def get_system_health(self) -> SystemHealth:
        """Get current system health metrics."""
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)

        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        available_memory_mb = memory.available / 1024 / 1024

        # Disk usage (root filesystem)
        disk = psutil.disk_usage('/')
        disk_usage_percent = (disk.used / disk.total) * 100
        free_disk_space_gb = disk.free / 1024 / 1024 / 1024

        # Load average
        load_average = list(os.getloadavg())

        return SystemHealth(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_usage_percent=disk_usage_percent,
            load_average=load_average,
            available_memory_mb=available_memory_mb,
            free_disk_space_gb=free_disk_space_gb
        )

    async def check_critical_paths(self) -> Dict[str, bool]:
        """Check access to critical paths."""
        results = {}

        for path in self.critical_paths:
            try:
                path_obj = Path(path)
                results[path] = path_obj.exists() and os.access(path, os.R_OK | os.W_OK)
            except Exception:
                results[path] = False

        return results

    async def diagnose_issues(self) -> List[str]:
        """Diagnose potential system issues."""
        issues = []

        # Get system health
        health = await self.get_system_health()

        # Check thresholds
        if health.cpu_percent > self.cpu_threshold_percent:
            issues.append(f"High CPU usage: {health.cpu_percent:.1f}%")

        if health.memory_percent > self.memory_threshold_percent:
            issues.append(f"High memory usage: {health.memory_percent:.1f}%")

        if health.disk_usage_percent > self.disk_threshold_percent:
            issues.append(f"High disk usage: {health.disk_usage_percent:.1f}%")

        # Check critical paths
        path_status = await self.check_critical_paths()
        for path, accessible in path_status.items():
            if not accessible:
                issues.append(f"Cannot access critical path: {path}")

        return issues

# Integration with file operations health check
async def comprehensive_health_check() -> Dict[str, Any]:
    """Comprehensive health check including system diagnostics."""
    diagnostics = SystemDiagnostics()

    # System health
    system_health = await diagnostics.get_system_health()
    system_issues = await diagnostics.diagnose_issues()

    # File operations health
    file_ops = FileOperations()
    file_health = await file_ops.health_check()

    # Overall status
    overall_healthy = (
        len(system_issues) == 0 and
        file_health.status == HealthStatusType.HEALTHY
    )

    return {
        "overall_status": "healthy" if overall_healthy else "unhealthy",
        "system": {
            "cpu_percent": system_health.cpu_percent,
            "memory_percent": system_health.memory_percent,
            "disk_usage_percent": system_health.disk_usage_percent,
            "load_average": system_health.load_average,
            "issues": system_issues
        },
        "file_operations": {
            "status": file_health.status.value,
            "checks": file_health.checks,
            "errors": file_health.errors
        },
        "timestamp": datetime.utcnow().isoformat()
    }
```

## Performance Monitoring

### Performance Metrics

```python
# performance_monitor.py
import time
import asyncio
from typing import Dict, Any, Optional
from collections import deque
import statistics

class PerformanceMonitor:
    """Monitor application performance metrics."""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.operation_times: Dict[str, deque] = {}
        self.error_counts: Dict[str, int] = {}
        self.total_operations: Dict[str, int] = {}

    def record_operation(self, operation: str, duration: float, success: bool = True) -> None:
        """Record operation performance."""
        # Initialize if needed
        if operation not in self.operation_times:
            self.operation_times[operation] = deque(maxlen=self.window_size)
            self.error_counts[operation] = 0
            self.total_operations[operation] = 0

        # Record timing
        self.operation_times[operation].append(duration)
        self.total_operations[operation] += 1

        # Record errors
        if not success:
            self.error_counts[operation] += 1

    def get_performance_stats(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """Get performance statistics."""
        if operation:
            return self._get_operation_stats(operation)

        # Return stats for all operations
        stats = {}
        for op in self.operation_times.keys():
            stats[op] = self._get_operation_stats(op)

        return stats

    def _get_operation_stats(self, operation: str) -> Dict[str, Any]:
        """Get statistics for a specific operation."""
        if operation not in self.operation_times:
            return {}

        times = list(self.operation_times[operation])
        if not times:
            return {}

        return {
            "count": len(times),
            "total_operations": self.total_operations[operation],
            "error_count": self.error_counts[operation],
            "error_rate": self.error_counts[operation] / self.total_operations[operation],
            "avg_duration_ms": statistics.mean(times) * 1000,
            "min_duration_ms": min(times) * 1000,
            "max_duration_ms": max(times) * 1000,
            "p50_duration_ms": statistics.median(times) * 1000,
            "p95_duration_ms": self._percentile(times, 0.95) * 1000,
            "p99_duration_ms": self._percentile(times, 0.99) * 1000
        }

    def _percentile(self, data: list, percentile: float) -> float:
        """Calculate percentile of data."""
        if not data:
            return 0.0

        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        return sorted_data[min(index, len(sorted_data) - 1)]

# Global performance monitor
perf_monitor = PerformanceMonitor()

# Decorator for automatic performance monitoring
def monitor_performance(operation_name: str):
    """Decorator to automatically monitor function performance."""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration = time.time() - start_time
                perf_monitor.record_operation(operation_name, duration, success)

        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True

            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration = time.time() - start_time
                perf_monitor.record_operation(operation_name, duration, success)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator
```

### Performance Alerting

```python
# alerts.py
from typing import Dict, Any, List, Callable
from dataclasses import dataclass
from enum import Enum
import logging

class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

@dataclass
class Alert:
    """Performance alert."""
    name: str
    severity: AlertSeverity
    message: str
    timestamp: float
    metadata: Dict[str, Any]

class AlertManager:
    """Manage performance alerts."""

    def __init__(self):
        self.alert_handlers: List[Callable[[Alert], None]] = []
        self.alert_history: List[Alert] = []
        self.max_history = 1000

    def add_handler(self, handler: Callable[[Alert], None]) -> None:
        """Add alert handler."""
        self.alert_handlers.append(handler)

    def trigger_alert(self, alert: Alert) -> None:
        """Trigger an alert."""
        self.alert_history.append(alert)

        # Trim history
        if len(self.alert_history) > self.max_history:
            self.alert_history = self.alert_history[-self.max_history:]

        # Send to handlers
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logging.error(f"Alert handler failed: {e}")

# Example alert handlers
def log_alert(alert: Alert) -> None:
    """Log alert to application logs."""
    logger = logging.getLogger("alerts")

    if alert.severity == AlertSeverity.CRITICAL:
        logger.critical(f"CRITICAL ALERT: {alert.message}")
    elif alert.severity == AlertSeverity.WARNING:
        logger.warning(f"WARNING: {alert.message}")
    else:
        logger.info(f"INFO: {alert.message}")

# Performance threshold monitoring
class PerformanceAlerting:
    """Monitor performance and trigger alerts."""

    def __init__(self, alert_manager: AlertManager):
        self.alert_manager = alert_manager
        self.thresholds = {
            "avg_response_time_ms": 1000,  # 1 second
            "error_rate": 0.05,            # 5%
            "p95_response_time_ms": 2000,  # 2 seconds
        }

    def check_performance_thresholds(self, stats: Dict[str, Any]) -> None:
        """Check performance stats against thresholds."""
        for operation, operation_stats in stats.items():
            # Check average response time
            if operation_stats.get("avg_duration_ms", 0) > self.thresholds["avg_response_time_ms"]:
                self.alert_manager.trigger_alert(Alert(
                    name="high_avg_response_time",
                    severity=AlertSeverity.WARNING,
                    message=f"High average response time for {operation}: {operation_stats['avg_duration_ms']:.1f}ms",
                    timestamp=time.time(),
                    metadata={"operation": operation, "value": operation_stats["avg_duration_ms"]}
                ))

            # Check error rate
            if operation_stats.get("error_rate", 0) > self.thresholds["error_rate"]:
                self.alert_manager.trigger_alert(Alert(
                    name="high_error_rate",
                    severity=AlertSeverity.CRITICAL,
                    message=f"High error rate for {operation}: {operation_stats['error_rate']:.1%}",
                    timestamp=time.time(),
                    metadata={"operation": operation, "value": operation_stats["error_rate"]}
                ))
```

## Security Operations

### Security Monitoring

```python
# security_monitor.py
import time
import hashlib
from typing import Dict, Any, List, Set
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

class SecurityEventType(Enum):
    """Types of security events."""
    PATH_TRAVERSAL_ATTEMPT = "path_traversal_attempt"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    SUSPICIOUS_FILE_ACCESS = "suspicious_file_access"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INVALID_FILE_TYPE = "invalid_file_type"
    LARGE_FILE_ATTEMPT = "large_file_attempt"

@dataclass
class SecurityEvent:
    """Security event record."""
    event_type: SecurityEventType
    timestamp: float
    source_ip: str
    user_id: str
    resource: str
    details: Dict[str, Any]
    severity: str

class SecurityMonitor:
    """Monitor and track security events."""

    def __init__(self, window_minutes: int = 60):
        self.window_minutes = window_minutes
        self.events: deque = deque()
        self.blocked_ips: Set[str] = set()
        self.suspicious_patterns: Dict[str, int] = defaultdict(int)

        # Thresholds
        self.max_events_per_ip = 100
        self.max_path_traversal_attempts = 5
        self.suspicious_file_patterns = ['.env', 'password', 'secret', 'key']

    def record_event(self, event: SecurityEvent) -> None:
        """Record a security event."""
        self.events.append(event)

        # Clean old events
        cutoff_time = time.time() - (self.window_minutes * 60)
        while self.events and self.events[0].timestamp < cutoff_time:
            self.events.popleft()

        # Analyze for threats
        self._analyze_threats(event)

    def _analyze_threats(self, event: SecurityEvent) -> None:
        """Analyze event for potential threats."""
        # Count events per IP
        ip_events = sum(1 for e in self.events if e.source_ip == event.source_ip)

        if ip_events > self.max_events_per_ip:
            self.blocked_ips.add(event.source_ip)
            logging.warning(f"Blocking IP {event.source_ip} due to excessive events")

        # Track path traversal attempts
        if event.event_type == SecurityEventType.PATH_TRAVERSAL_ATTEMPT:
            key = f"{event.source_ip}:path_traversal"
            self.suspicious_patterns[key] += 1

            if self.suspicious_patterns[key] > self.max_path_traversal_attempts:
                self.blocked_ips.add(event.source_ip)
                logging.critical(f"Blocking IP {event.source_ip} due to repeated path traversal attempts")

    def is_ip_blocked(self, ip: str) -> bool:
        """Check if IP is blocked."""
        return ip in self.blocked_ips

    def get_security_summary(self) -> Dict[str, Any]:
        """Get security summary."""
        events_by_type = defaultdict(int)
        events_by_ip = defaultdict(int)

        for event in self.events:
            events_by_type[event.event_type.value] += 1
            events_by_ip[event.source_ip] += 1

        return {
            "total_events": len(self.events),
            "events_by_type": dict(events_by_type),
            "top_sources": dict(sorted(events_by_ip.items(), key=lambda x: x[1], reverse=True)[:10]),
            "blocked_ips": list(self.blocked_ips),
            "window_minutes": self.window_minutes
        }

# Global security monitor
security_monitor = SecurityMonitor()

# Security middleware
def security_middleware(func):
    """Middleware to monitor security events."""
    async def wrapper(*args, **kwargs):
        # Extract request context
        request_context = kwargs.get('request_context', {})
        source_ip = request_context.get('source_ip', 'unknown')
        user_id = request_context.get('user_id', 'anonymous')

        # Check if IP is blocked
        if security_monitor.is_ip_blocked(source_ip):
            raise PermissionError(f"Access denied for IP {source_ip}")

        try:
            return await func(*args, **kwargs)
        except SecurityValidationError as e:
            # Record security event
            security_monitor.record_event(SecurityEvent(
                event_type=SecurityEventType.PATH_TRAVERSAL_ATTEMPT,
                timestamp=time.time(),
                source_ip=source_ip,
                user_id=user_id,
                resource=str(args[0]) if args else "unknown",
                details={"error": str(e)},
                severity="high"
            ))
            raise

    return wrapper
```

## Troubleshooting Guide

### Common Issues and Solutions

#### Issue: High Memory Usage

**Symptoms:**

- Memory usage consistently above 80%
- OutOfMemory errors
- Slow response times

**Diagnosis:**

```python
# Check memory usage
import psutil
memory = psutil.virtual_memory()
print(f"Memory usage: {memory.percent}%")
print(f"Available: {memory.available / 1024 / 1024:.1f} MB")

# Check for memory leaks in file operations
import gc
gc.collect()
print(f"Garbage collection objects: {len(gc.get_objects())}")
```

**Solutions:**

1. **Reduce file size limits:**

   ```python
   file_ops = FileOperations(max_file_size=1024*1024)  # 1MB limit
   ```

2. **Implement streaming for large files:**

   ```python
   async def stream_large_file(path: str):
       async with aiofiles.open(path, 'rb') as f:
           while chunk := await f.read(8192):
               yield chunk
   ```

3. **Clear caches regularly:**
   ```python
   # Clear dependency cache
   decorator_instance._dependency_cache.clear()
   ```

#### Issue: Connection Timeouts

**Symptoms:**

- Registry connection failures
- Dependency injection timeouts
- Health check failures

**Diagnosis:**

```bash
# Check network connectivity
ping registry-host
telnet registry-host 8080

# Check DNS resolution
nslookup registry-host

# Check firewall rules
iptables -L
```

**Solutions:**

1. **Increase timeouts:**

   ```python
   @mesh_agent(
       timeout=60,  # Increase timeout
       retry_attempts=5  # More retries
   )
   ```

2. **Enable fallback mode:**

   ```python
   @mesh_agent(fallback_mode=True)
   ```

3. **Configure retry strategy:**
   ```python
   retry_config = RetryConfig(
       strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
       max_retries=5,
       initial_delay_ms=2000,
       max_delay_ms=30000
   )
   ```

#### Issue: File Permission Errors

**Symptoms:**

- PermissionError exceptions
- Unable to read/write files
- Directory listing failures

**Diagnosis:**

```bash
# Check file permissions
ls -la /path/to/file

# Check directory permissions
ls -ld /path/to/directory

# Check user/group
id

# Check ACLs (if applicable)
getfacl /path/to/file
```

**Solutions:**

1. **Fix file permissions:**

   ```bash
   chmod 644 /path/to/file
   chmod 755 /path/to/directory
   ```

2. **Run as correct user:**

   ```bash
   sudo chown app:app /path/to/directory
   ```

3. **Use appropriate base directory:**
   ```python
   file_ops = FileOperations(base_directory="/app/data")
   ```

### Debugging Tools

#### Debug Mode Configuration

```python
# debug_config.py
import logging
import os

def enable_debug_mode():
    """Enable comprehensive debugging."""

    # Set debug logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )

    # Enable asyncio debug mode
    os.environ['PYTHONASYNCIODEBUG'] = '1'

    # Enable mesh agent debug logging
    logging.getLogger('mcp_mesh_sdk').setLevel(logging.DEBUG)

    # Enable dependency injection debugging
    logging.getLogger('mcp_mesh_sdk.decorators').setLevel(logging.DEBUG)

    print("Debug mode enabled")

# Debugging utilities
async def debug_mesh_state(agent_function):
    """Debug mesh agent state."""
    if hasattr(agent_function, '_mesh_agent_metadata'):
        metadata = agent_function._mesh_agent_metadata
        decorator_instance = metadata['decorator_instance']

        print(f"Agent: {decorator_instance.agent_name}")
        print(f"Capabilities: {decorator_instance.capabilities}")
        print(f"Dependencies: {decorator_instance.dependencies}")
        print(f"Initialized: {decorator_instance._initialized}")
        print(f"Cached dependencies: {list(decorator_instance._dependency_cache.keys())}")
        print(f"Registry client: {decorator_instance._registry_client is not None}")
```

#### Performance Profiling

```python
# profiling.py
import cProfile
import pstats
import io
from functools import wraps

def profile_function(func):
    """Profile function execution."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()

        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            profiler.disable()

            # Generate report
            s = io.StringIO()
            stats = pstats.Stats(profiler, stream=s)
            stats.sort_stats('cumulative')
            stats.print_stats(20)  # Top 20 functions

            print(f"Profile for {func.__name__}:")
            print(s.getvalue())

    return wrapper

# Usage
@profile_function
@mesh_agent(capabilities=["file_read"])
async def profiled_read_file(path: str):
    return await file_ops.read_file(path)
```

## Backup and Recovery

### Configuration Backup

```python
# backup_config.py
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

class ConfigurationBackup:
    """Backup and restore configuration."""

    def __init__(self, backup_dir: str = "/backup/config"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def backup_configuration(self) -> str:
        """Backup current configuration."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"config_backup_{timestamp}"
        backup_path = self.backup_dir / backup_name

        # Create backup directory
        backup_path.mkdir(exist_ok=True)

        # Backup configuration files
        config_files = [
            "pyproject.toml",
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-prod.txt"
        ]

        for config_file in config_files:
            if os.path.exists(config_file):
                shutil.copy2(config_file, backup_path / config_file)

        # Backup environment variables
        env_backup = {
            key: value for key, value in os.environ.items()
            if key.startswith(('MESH_', 'MCP_', 'LOG_', 'CACHE_'))
        }

        with open(backup_path / "environment.json", "w") as f:
            json.dump(env_backup, f, indent=2)

        # Create backup manifest
        manifest = {
            "timestamp": timestamp,
            "files": config_files,
            "environment_variables": list(env_backup.keys())
        }

        with open(backup_path / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        return str(backup_path)

    def restore_configuration(self, backup_name: str) -> None:
        """Restore configuration from backup."""
        backup_path = self.backup_dir / backup_name

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_name}")

        # Load manifest
        manifest_path = backup_path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("Backup manifest not found")

        with open(manifest_path) as f:
            manifest = json.load(f)

        # Restore configuration files
        for config_file in manifest["files"]:
            backup_file = backup_path / config_file
            if backup_file.exists():
                shutil.copy2(backup_file, config_file)
                print(f"Restored: {config_file}")

        # Restore environment variables
        env_path = backup_path / "environment.json"
        if env_path.exists():
            with open(env_path) as f:
                env_vars = json.load(f)

            print("Environment variables from backup:")
            for key, value in env_vars.items():
                print(f"  export {key}={value}")

    def list_backups(self) -> List[Dict[str, Any]]:
        """List available backups."""
        backups = []

        for backup_dir in self.backup_dir.iterdir():
            if backup_dir.is_dir() and backup_dir.name.startswith("config_backup_"):
                manifest_path = backup_dir / "manifest.json"
                if manifest_path.exists():
                    with open(manifest_path) as f:
                        manifest = json.load(f)

                    backups.append({
                        "name": backup_dir.name,
                        "timestamp": manifest["timestamp"],
                        "path": str(backup_dir),
                        "files_count": len(manifest["files"])
                    })

        return sorted(backups, key=lambda x: x["timestamp"], reverse=True)
```

### Data Recovery Procedures

```bash
#!/bin/bash
# recovery_script.sh

# Data recovery procedures

echo "MCP Mesh SDK Recovery Script"
echo "============================"

# Check if backup directory exists
BACKUP_DIR="/backup"
if [ ! -d "$BACKUP_DIR" ]; then
    echo "Error: Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# List available backups
echo "Available backups:"
ls -la $BACKUP_DIR/

# Recovery options
echo ""
echo "Recovery options:"
echo "1. Restore configuration"
echo "2. Restore data files"
echo "3. Full system restore"
echo "4. Verify backup integrity"

read -p "Select option (1-4): " OPTION

case $OPTION in
    1)
        echo "Restoring configuration..."
        python3 -c "
from backup_config import ConfigurationBackup
backup = ConfigurationBackup()
backups = backup.list_backups()
if backups:
    print('Available configuration backups:')
    for i, b in enumerate(backups):
        print(f'{i}: {b[\"name\"]} ({b[\"timestamp\"]})')
    choice = int(input('Select backup: '))
    backup.restore_configuration(backups[choice]['name'])
else:
    print('No configuration backups found')
"
        ;;
    2)
        echo "Restoring data files..."
        # Implement data file restoration
        ;;
    3)
        echo "Full system restore..."
        # Implement full system restoration
        ;;
    4)
        echo "Verifying backup integrity..."
        # Implement backup verification
        ;;
    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo "Recovery completed"
```

## Update and Upgrade Procedures

### Rolling Updates

```bash
#!/bin/bash
# rolling_update.sh

# Rolling update procedure for production deployment

set -e

echo "MCP Mesh SDK Rolling Update"
echo "=========================="

# Configuration
NEW_VERSION="$1"
HEALTH_CHECK_URL="http://localhost:8080/health"
READINESS_CHECK_URL="http://localhost:8080/ready"
ROLLBACK_ON_FAILURE=true

if [ -z "$NEW_VERSION" ]; then
    echo "Usage: $0 <new_version>"
    exit 1
fi

echo "Updating to version: $NEW_VERSION"

# Pre-update checks
echo "Running pre-update checks..."

# Check current health
if ! curl -f "$HEALTH_CHECK_URL" > /dev/null 2>&1; then
    echo "Error: Current deployment is unhealthy"
    exit 1
fi

# Backup current configuration
echo "Backing up current configuration..."
python3 -c "
from backup_config import ConfigurationBackup
backup = ConfigurationBackup()
backup_path = backup.backup_configuration()
print(f'Configuration backed up to: {backup_path}')
"

# Update procedure
echo "Starting update..."

# Download new version
pip install --upgrade mcp-mesh-sdk==$NEW_VERSION

# Restart services (example with systemd)
if command -v systemctl > /dev/null; then
    echo "Restarting services..."
    sudo systemctl restart mcp-mesh-sdk

    # Wait for service to start
    sleep 10

    # Check service status
    if ! sudo systemctl is-active mcp-mesh-sdk > /dev/null; then
        echo "Error: Service failed to start"
        if [ "$ROLLBACK_ON_FAILURE" = true ]; then
            echo "Rolling back..."
            # Implement rollback logic
        fi
        exit 1
    fi
fi

# Health checks
echo "Running post-update health checks..."

# Wait for readiness
TIMEOUT=60
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    if curl -f "$READINESS_CHECK_URL" > /dev/null 2>&1; then
        echo "Service is ready"
        break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "Error: Service failed readiness check"
    if [ "$ROLLBACK_ON_FAILURE" = true ]; then
        echo "Rolling back..."
        # Implement rollback logic
    fi
    exit 1
fi

# Final health check
if curl -f "$HEALTH_CHECK_URL" > /dev/null 2>&1; then
    echo "Update completed successfully"
    echo "New version: $NEW_VERSION"
else
    echo "Error: Post-update health check failed"
    exit 1
fi
```

### Database Migration

```python
# migration.py
from typing import List, Dict, Any
import logging
import json
from pathlib import Path

class MigrationManager:
    """Manage data migrations between versions."""

    def __init__(self, migration_dir: str = "migrations"):
        self.migration_dir = Path(migration_dir)
        self.migration_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger(__name__)

    def create_migration(self, name: str, migration_func: callable) -> None:
        """Create a new migration."""
        migration_file = self.migration_dir / f"{name}.py"

        # Generate migration template
        template = f'''
"""
Migration: {name}
Generated at: {datetime.now().isoformat()}
"""

async def migrate():
    """Perform migration."""
    # Implementation here
    pass

async def rollback():
    """Rollback migration."""
    # Implementation here
    pass
'''

        with open(migration_file, "w") as f:
            f.write(template)

        self.logger.info(f"Created migration: {name}")

    def run_migrations(self) -> None:
        """Run pending migrations."""
        # Get applied migrations
        applied_migrations = self._get_applied_migrations()

        # Get available migrations
        available_migrations = self._get_available_migrations()

        # Run pending migrations
        for migration in available_migrations:
            if migration not in applied_migrations:
                self.logger.info(f"Running migration: {migration}")
                self._run_migration(migration)
                self._mark_migration_applied(migration)

    def _get_applied_migrations(self) -> List[str]:
        """Get list of applied migrations."""
        migration_log = self.migration_dir / "applied_migrations.json"
        if migration_log.exists():
            with open(migration_log) as f:
                return json.load(f)
        return []

    def _get_available_migrations(self) -> List[str]:
        """Get list of available migrations."""
        migrations = []
        for migration_file in self.migration_dir.glob("*.py"):
            if migration_file.name != "__init__.py":
                migrations.append(migration_file.stem)
        return sorted(migrations)

    def _run_migration(self, migration_name: str) -> None:
        """Run a specific migration."""
        # Dynamic import and execution
        # Implementation depends on migration format
        pass

    def _mark_migration_applied(self, migration_name: str) -> None:
        """Mark migration as applied."""
        applied_migrations = self._get_applied_migrations()
        applied_migrations.append(migration_name)

        migration_log = self.migration_dir / "applied_migrations.json"
        with open(migration_log, "w") as f:
            json.dump(applied_migrations, f, indent=2)
```

## Incident Response

### Incident Response Plan

```python
# incident_response.py
from enum import Enum
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import logging

class IncidentSeverity(Enum):
    """Incident severity levels."""
    P1_CRITICAL = "P1_Critical"    # System down, data loss
    P2_HIGH = "P2_High"            # Major functionality impacted
    P3_MEDIUM = "P3_Medium"        # Minor functionality impacted
    P4_LOW = "P4_Low"              # Cosmetic issues

@dataclass
class Incident:
    """Incident record."""
    id: str
    title: str
    description: str
    severity: IncidentSeverity
    status: str
    created_at: datetime
    assigned_to: str
    components_affected: List[str]
    actions_taken: List[str]
    resolution: str = ""

class IncidentManager:
    """Manage incidents and responses."""

    def __init__(self):
        self.incidents: Dict[str, Incident] = {}
        self.escalation_rules = {
            IncidentSeverity.P1_CRITICAL: 5,   # 5 minutes
            IncidentSeverity.P2_HIGH: 15,      # 15 minutes
            IncidentSeverity.P3_MEDIUM: 60,    # 1 hour
            IncidentSeverity.P4_LOW: 240       # 4 hours
        }
        self.logger = logging.getLogger(__name__)

    def create_incident(
        self,
        title: str,
        description: str,
        severity: IncidentSeverity,
        components_affected: List[str]
    ) -> str:
        """Create new incident."""
        incident_id = f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        incident = Incident(
            id=incident_id,
            title=title,
            description=description,
            severity=severity,
            status="open",
            created_at=datetime.now(),
            assigned_to="on-call-engineer",
            components_affected=components_affected,
            actions_taken=[]
        )

        self.incidents[incident_id] = incident

        # Trigger alerts based on severity
        self._trigger_incident_alerts(incident)

        self.logger.critical(f"Incident created: {incident_id} - {title}")
        return incident_id

    def add_action(self, incident_id: str, action: str) -> None:
        """Add action to incident."""
        if incident_id in self.incidents:
            self.incidents[incident_id].actions_taken.append({
                "timestamp": datetime.now().isoformat(),
                "action": action
            })
            self.logger.info(f"Action added to {incident_id}: {action}")

    def resolve_incident(self, incident_id: str, resolution: str) -> None:
        """Resolve incident."""
        if incident_id in self.incidents:
            self.incidents[incident_id].status = "resolved"
            self.incidents[incident_id].resolution = resolution
            self.logger.info(f"Incident resolved: {incident_id}")

    def _trigger_incident_alerts(self, incident: Incident) -> None:
        """Trigger alerts for incident."""
        # Implementation depends on alerting system
        # Could send to PagerDuty, Slack, email, etc.
        self.logger.critical(f"INCIDENT ALERT: {incident.severity.value} - {incident.title}")

# Automated incident detection
class IncidentDetector:
    """Detect incidents automatically."""

    def __init__(self, incident_manager: IncidentManager):
        self.incident_manager = incident_manager
        self.error_thresholds = {
            "error_rate": 0.1,          # 10% error rate
            "response_time": 5000,      # 5 seconds
            "memory_usage": 0.9,        # 90% memory usage
            "disk_usage": 0.95          # 95% disk usage
        }

    def check_for_incidents(self, metrics: Dict[str, Any]) -> None:
        """Check metrics for potential incidents."""

        # Check error rate
        for operation, stats in metrics.get("operations", {}).items():
            error_rate = stats.get("error_rate", 0)
            if error_rate > self.error_thresholds["error_rate"]:
                self.incident_manager.create_incident(
                    title=f"High Error Rate: {operation}",
                    description=f"Error rate for {operation} is {error_rate:.1%}",
                    severity=IncidentSeverity.P2_HIGH,
                    components_affected=[operation]
                )

        # Check response time
        for operation, stats in metrics.get("operations", {}).items():
            avg_time = stats.get("avg_duration_ms", 0)
            if avg_time > self.error_thresholds["response_time"]:
                self.incident_manager.create_incident(
                    title=f"Slow Response Time: {operation}",
                    description=f"Average response time for {operation} is {avg_time:.1f}ms",
                    severity=IncidentSeverity.P3_MEDIUM,
                    components_affected=[operation]
                )

        # Check system resources
        system_metrics = metrics.get("system", {})

        memory_usage = system_metrics.get("memory_percent", 0) / 100
        if memory_usage > self.error_thresholds["memory_usage"]:
            self.incident_manager.create_incident(
                title="High Memory Usage",
                description=f"Memory usage is {memory_usage:.1%}",
                severity=IncidentSeverity.P2_HIGH,
                components_affected=["system"]
            )

        disk_usage = system_metrics.get("disk_usage_percent", 0) / 100
        if disk_usage > self.error_thresholds["disk_usage"]:
            self.incident_manager.create_incident(
                title="High Disk Usage",
                description=f"Disk usage is {disk_usage:.1%}",
                severity=IncidentSeverity.P1_CRITICAL,
                components_affected=["system"]
            )
```

### Runbooks

#### High Memory Usage Runbook

````markdown
# Runbook: High Memory Usage

## Incident Description

Memory usage has exceeded the threshold (typically 85-90%).

## Immediate Actions

1. **Check current memory usage:**
   ```bash
   free -h
   ps aux --sort=-%mem | head -20
   ```
````

2. **Identify memory-consuming processes:**

   ```bash
   top -o %MEM
   ```

3. **Check for memory leaks:**
   ```python
   import gc
   gc.collect()
   print(f"Objects: {len(gc.get_objects())}")
   ```

## Investigation Steps

1. Check application logs for memory-related errors
2. Review recent deployments or configuration changes
3. Analyze garbage collection metrics
4. Check for large file operations

## Resolution Actions

1. **Restart application if safe:**

   ```bash
   sudo systemctl restart mcp-mesh-sdk
   ```

2. **Reduce memory limits:**

   ```python
   file_ops = FileOperations(max_file_size=1024*1024)  # 1MB
   ```

3. **Clear caches:**

   ```python
   decorator_instance._dependency_cache.clear()
   ```

4. **Scale horizontally if possible**

## Prevention

- Implement memory monitoring alerts
- Regular garbage collection analysis
- Code review for memory leaks
- Load testing with memory profiling

```

This comprehensive maintenance and operations documentation provides the foundation for running the MCP Mesh SDK reliably in production environments.
```

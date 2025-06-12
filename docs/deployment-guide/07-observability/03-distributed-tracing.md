# Distributed Tracing

> Trace requests across your distributed MCP Mesh system with OpenTelemetry and Jaeger

## Overview

Distributed tracing provides end-to-end visibility into request flows across multiple MCP Mesh agents. This guide covers implementing OpenTelemetry instrumentation, deploying Jaeger for trace storage and visualization, correlating traces with logs and metrics, and analyzing performance bottlenecks. You'll learn to trace complex multi-agent interactions and debug distributed system issues.

Proper distributed tracing is essential for understanding request flows, identifying bottlenecks, and troubleshooting issues in your MCP Mesh deployment.

## Key Concepts

- **Spans**: Individual operations within a trace
- **Traces**: Complete request flow across services
- **Context Propagation**: Passing trace context between agents
- **Sampling**: Strategies for managing trace volume
- **Correlation**: Linking traces with logs and metrics

## Step-by-Step Guide

### Step 1: Deploy Jaeger and OpenTelemetry

Set up the tracing infrastructure:

```bash
# Install Jaeger Operator
kubectl create namespace observability
kubectl create -f https://github.com/jaegertracing/jaeger-operator/releases/download/v1.51.0/jaeger-operator.yaml -n observability

# Wait for operator to be ready
kubectl wait --for=condition=available deployment/jaeger-operator -n observability --timeout=300s

# Deploy Jaeger instance
cat > jaeger-instance.yaml << 'EOF'
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: mcp-mesh-jaeger
  namespace: observability
spec:
  strategy: production

  ingress:
    enabled: true
    annotations:
      kubernetes.io/ingress.class: nginx
    hosts:
    - jaeger.mcp-mesh.local

  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch:9200
        index-prefix: mcp-mesh
    esIndexCleaner:
      enabled: true
      numberOfDays: 7
      schedule: "55 23 * * *"

  collector:
    replicas: 3
    resources:
      limits:
        memory: 2Gi
        cpu: 1000m
      requests:
        memory: 512Mi
        cpu: 200m
    autoscale: true
    maxReplicas: 10

  query:
    replicas: 2
    resources:
      limits:
        memory: 1Gi
        cpu: 500m
      requests:
        memory: 256Mi
        cpu: 100m

  agent:
    strategy: DaemonSet
    annotations:
      prometheus.io/scrape: "true"
      prometheus.io/port: "14271"
EOF

kubectl apply -f jaeger-instance.yaml

# Deploy OpenTelemetry Collector
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

cat > otel-values.yaml << 'EOF'
mode: deployment

config:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

    prometheus:
      config:
        scrape_configs:
        - job_name: 'otel-collector'
          scrape_interval: 10s
          static_configs:
          - targets: ['0.0.0.0:8888']

  processors:
    batch:
      timeout: 1s
      send_batch_size: 1024

    memory_limiter:
      check_interval: 1s
      limit_mib: 1024
      spike_limit_mib: 256

    attributes:
      actions:
      - key: environment
        value: production
        action: upsert
      - key: service.namespace
        value: mcp-mesh
        action: upsert

    resource:
      attributes:
      - key: service.instance.id
        from_attribute: k8s.pod.name
        action: upsert

    tail_sampling:
      decision_wait: 10s
      num_traces: 100000
      policies:
      - name: errors-policy
        type: status_code
        status_code:
          status_codes: [ERROR]
      - name: slow-traces-policy
        type: latency
        latency:
          threshold_ms: 1000
      - name: probabilistic-policy
        type: probabilistic
        probabilistic:
          sampling_percentage: 10

  exporters:
    jaeger:
      endpoint: mcp-mesh-jaeger-collector.observability:14250
      tls:
        insecure: true

    prometheus:
      endpoint: 0.0.0.0:8889
      namespace: otel
      const_labels:
        service: otel-collector

    logging:
      loglevel: info

  service:
    pipelines:
      traces:
        receivers: [otlp]
        processors: [memory_limiter, batch, attributes, resource, tail_sampling]
        exporters: [jaeger, logging]

      metrics:
        receivers: [prometheus, otlp]
        processors: [memory_limiter, batch]
        exporters: [prometheus]

resources:
  limits:
    memory: 2Gi
    cpu: 1000m
  requests:
    memory: 512Mi
    cpu: 200m

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 80
  targetMemoryUtilizationPercentage: 80
EOF

helm install otel-collector open-telemetry/opentelemetry-collector \
  --namespace observability \
  --values otel-values.yaml
```

### Step 2: Implement OpenTelemetry in MCP Mesh

Add tracing instrumentation to MCP Mesh components:

```python
# mcp_mesh/tracing.py
from opentelemetry import trace, propagate, baggage
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.aiohttp import AioHttpClientInstrumentor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace import Status, StatusCode
import os
from functools import wraps
import asyncio

# Initialize tracing
def init_tracing(service_name: str, endpoint: str = None):
    """Initialize OpenTelemetry tracing"""

    # Create resource
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        "k8s.namespace.name": os.getenv("K8S_NAMESPACE", "mcp-mesh"),
        "k8s.pod.name": os.getenv("HOSTNAME", "unknown"),
        "k8s.node.name": os.getenv("NODE_NAME", "unknown"),
    })

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Configure exporter
    if endpoint is None:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT",
                           "otel-collector.observability:4317")

    otlp_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=True,
    )

    # Add span processor
    span_processor = BatchSpanProcessor(
        otlp_exporter,
        max_queue_size=2048,
        max_export_batch_size=512,
        max_export_interval_millis=5000,
    )
    provider.add_span_processor(span_processor)

    # Set global tracer provider
    trace.set_tracer_provider(provider)

    # Instrument libraries
    RequestsInstrumentor().instrument()
    AioHttpClientInstrumentor().instrument()

    # Set up propagator
    propagate.set_global_textmap(TraceContextTextMapPropagator())

    return trace.get_tracer(service_name)

# Tracing decorator for async functions
def trace_async(span_name: str = None, attributes: dict = None):
    """Decorator to trace async functions"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = trace.get_tracer(__name__)

            # Use function name if span name not provided
            name = span_name or f"{func.__module__}.{func.__name__}"

            with tracer.start_as_current_span(
                name,
                kind=trace.SpanKind.INTERNAL,
                attributes=attributes or {}
            ) as span:
                try:
                    # Add function arguments as attributes
                    span.set_attribute("function.args", str(args))
                    span.set_attribute("function.kwargs", str(kwargs))

                    # Execute function
                    result = await func(*args, **kwargs)

                    # Mark success
                    span.set_status(Status(StatusCode.OK))

                    return result

                except Exception as e:
                    # Record exception
                    span.record_exception(e)
                    span.set_status(
                        Status(StatusCode.ERROR, str(e))
                    )
                    raise

        return wrapper
    return decorator

# Context propagation for MCP Mesh
class MCPMeshTraceContext:
    """Handle trace context propagation in MCP Mesh"""

    @staticmethod
    def inject_context(headers: dict) -> dict:
        """Inject trace context into headers"""
        propagate.inject(headers)

        # Add MCP Mesh specific baggage
        baggage_ctx = baggage.set_baggage(
            "mcp.mesh.agent",
            os.getenv("AGENT_NAME", "unknown")
        )
        baggage.get_all(baggage_ctx)

        return headers

    @staticmethod
    def extract_context(headers: dict):
        """Extract trace context from headers"""
        return propagate.extract(headers)

# Instrumented MCP Mesh Agent
class TracedMCPAgent:
    def __init__(self, name: str):
        self.name = name
        self.tracer = init_tracing(f"mcp-mesh-{name}")

    @trace_async("agent.initialize")
    async def initialize(self):
        """Initialize agent with tracing"""
        span = trace.get_current_span()
        span.set_attribute("agent.name", self.name)
        span.set_attribute("agent.type", "mcp-mesh")

        # Initialization logic
        await self._connect_to_registry()
        await self._register_capabilities()

    @trace_async("agent.handle_request")
    async def handle_request(self, request: dict, context: dict = None):
        """Handle incoming request with tracing"""
        span = trace.get_current_span()

        # Extract trace context if provided
        if context and "headers" in context:
            ctx = MCPMeshTraceContext.extract_context(context["headers"])
            span.set_attribute("parent.trace_id", ctx.get("traceparent", ""))

        # Set request attributes
        span.set_attribute("request.method", request.get("method"))
        span.set_attribute("request.id", request.get("id"))
        span.set_attribute("request.params", str(request.get("params", {})))

        # Add custom attributes
        span.set_attribute("agent.name", self.name)
        span.set_attribute("agent.version", "1.0.0")

        # Process request
        with self.tracer.start_as_current_span(
            f"process_{request.get('method')}",
            kind=trace.SpanKind.INTERNAL
        ) as process_span:

            # Simulate processing
            await asyncio.sleep(0.1)

            # Call external service
            response = await self._call_external_service(request)

            process_span.set_attribute("response.status", "success")

        return response

    @trace_async("agent.call_external")
    async def _call_external_service(self, request: dict):
        """Call external service with trace propagation"""
        span = trace.get_current_span()

        # Prepare headers with trace context
        headers = {}
        MCPMeshTraceContext.inject_context(headers)

        # Add span link to related traces
        link_context = trace.Link(
            span.get_span_context(),
            attributes={"link.type": "external_call"}
        )

        with self.tracer.start_as_current_span(
            "external_api_call",
            kind=trace.SpanKind.CLIENT,
            links=[link_context]
        ) as api_span:

            api_span.set_attribute("http.method", "POST")
            api_span.set_attribute("http.url", "https://api.example.com/data")
            api_span.set_attribute("http.request.body.size", len(str(request)))

            # Simulate API call
            await asyncio.sleep(0.2)

            api_span.set_attribute("http.status_code", 200)
            api_span.set_attribute("http.response.body.size", 1024)

        return {"status": "success", "data": "example"}

# Registry with distributed tracing
class TracedRegistry:
    def __init__(self):
        self.tracer = init_tracing("mcp-mesh-registry")
        self.agents = {}

    @trace_async("registry.register_agent")
    async def register_agent(self, agent_info: dict):
        """Register agent with tracing"""
        span = trace.get_current_span()

        agent_name = agent_info.get("name")
        span.set_attribute("agent.name", agent_name)
        span.set_attribute("agent.capabilities",
                         str(agent_info.get("capabilities", [])))

        # Store agent info
        self.agents[agent_name] = agent_info

        # Create event
        span.add_event(
            "agent_registered",
            attributes={
                "agent.name": agent_name,
                "agent.endpoint": agent_info.get("endpoint")
            }
        )

        return {"status": "registered", "agent_id": agent_name}

    @trace_async("registry.route_request")
    async def route_request(self, request: dict):
        """Route request to appropriate agent"""
        span = trace.get_current_span()

        # Determine target agent
        target_agent = self._select_agent(request)
        span.set_attribute("target.agent", target_agent)

        # Create child span for agent call
        with self.tracer.start_as_current_span(
            f"call_agent_{target_agent}",
            kind=trace.SpanKind.CLIENT
        ) as agent_span:

            # Propagate context
            headers = {}
            MCPMeshTraceContext.inject_context(headers)

            # Call agent
            response = await self._call_agent(
                target_agent,
                request,
                {"headers": headers}
            )

            agent_span.set_attribute("response.status",
                                   response.get("status"))

        return response
```

### Step 3: Configure Trace Sampling

Implement intelligent sampling strategies:

```yaml
# trace-sampling-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-sampling-config
  namespace: observability
data:
  sampling.yaml: |
    # Tail-based sampling configuration
    sampling_rules:
      # Always sample errors
      - name: sample-errors
        type: status_code
        status_code:
          status_codes: [ERROR, UNSET]
        decision: SAMPLE

      # Sample slow requests
      - name: sample-slow
        type: latency
        latency:
          threshold_ms: 500
        decision: SAMPLE

      # Sample by agent
      - name: sample-critical-agents
        type: string_attribute
        string_attribute:
          key: agent.name
          values: ["payment-agent", "auth-agent"]
        decision: SAMPLE

      # Rate-based sampling for high-volume agents
      - name: rate-limit-weather
        type: rate_limiting
        rate_limiting:
          spans_per_second: 100
        string_attribute:
          key: agent.name
          values: ["weather-agent"]

      # Probabilistic sampling for everything else
      - name: probabilistic-fallback
        type: probabilistic
        probabilistic:
          sampling_percentage: 1.0
        decision: SAMPLE

    # Composite sampling
    composite:
      max_traces_per_second: 1000
      policy_order:
        - sample-errors
        - sample-slow
        - sample-critical-agents
        - rate-limit-weather
        - probabilistic-fallback
```

### Step 4: Create Trace Analysis Dashboards

Build Grafana dashboards for trace metrics:

```json
{
  "dashboard": {
    "title": "MCP Mesh Trace Analysis",
    "uid": "mcp-mesh-traces",
    "panels": [
      {
        "title": "Trace Overview",
        "type": "stat",
        "gridPos": { "h": 4, "w": 6, "x": 0, "y": 0 },
        "targets": [
          {
            "expr": "sum(rate(traces_spanmetrics_calls_total[5m]))",
            "legendFormat": "Spans/sec"
          }
        ]
      },

      {
        "title": "Service Dependency Graph",
        "type": "nodeGraph",
        "gridPos": { "h": 12, "w": 24, "x": 0, "y": 4 },
        "targets": [
          {
            "expr": "sum by (service_name, span_name) (rate(traces_spanmetrics_calls_total[5m]))",
            "format": "table"
          }
        ],
        "options": {
          "nodes": {
            "mainStatUnit": "ops"
          },
          "edges": {
            "mainStatUnit": "ops"
          }
        }
      },

      {
        "title": "Latency Distribution",
        "type": "heatmap",
        "gridPos": { "h": 10, "w": 12, "x": 0, "y": 16 },
        "targets": [
          {
            "expr": "sum by (le) (increase(traces_spanmetrics_latency_bucket[5m]))",
            "format": "heatmap"
          }
        ]
      },

      {
        "title": "Error Rate by Service",
        "type": "timeseries",
        "gridPos": { "h": 10, "w": 12, "x": 12, "y": 16 },
        "targets": [
          {
            "expr": "sum by (service_name) (rate(traces_spanmetrics_calls_total{status_code=\"STATUS_CODE_ERROR\"}[5m])) / sum by (service_name) (rate(traces_spanmetrics_calls_total[5m])) * 100",
            "legendFormat": "{{service_name}}"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "custom": {
              "drawStyle": "line",
              "lineWidth": 2,
              "fillOpacity": 10
            }
          }
        }
      },

      {
        "title": "Trace Exemplars",
        "type": "table",
        "gridPos": { "h": 8, "w": 24, "x": 0, "y": 26 },
        "targets": [
          {
            "expr": "topk(10, traces_spanmetrics_latency_sum / traces_spanmetrics_latency_count)",
            "format": "table",
            "instant": true
          }
        ],
        "transformations": [
          {
            "id": "organize",
            "options": {
              "excludeByName": {
                "Time": true
              },
              "renameByName": {
                "service_name": "Service",
                "span_name": "Operation",
                "Value": "Avg Latency (ms)"
              }
            }
          }
        ],
        "options": {
          "showHeader": true,
          "cellHeight": "sm"
        },
        "fieldConfig": {
          "overrides": [
            {
              "matcher": { "id": "byName", "options": "Avg Latency (ms)" },
              "properties": [
                {
                  "id": "unit",
                  "value": "ms"
                },
                {
                  "id": "custom.displayMode",
                  "value": "color-background"
                },
                {
                  "id": "thresholds",
                  "value": {
                    "mode": "absolute",
                    "steps": [
                      { "color": "green", "value": 0 },
                      { "color": "yellow", "value": 100 },
                      { "color": "red", "value": 500 }
                    ]
                  }
                },
                {
                  "id": "links",
                  "value": [
                    {
                      "title": "View traces",
                      "url": "http://jaeger.mcp-mesh.local/search?service=${__data.fields.Service}&operation=${__data.fields.Operation}&limit=20"
                    }
                  ]
                }
              ]
            }
          ]
        }
      }
    ]
  }
}
```

### Step 5: Implement Trace-Metric Correlation

Link traces with metrics and logs:

```python
# correlation.py
from opentelemetry import trace, metrics
from prometheus_client import Counter, Histogram
import logging
import json

# Configure structured logging with trace context
class TraceContextFilter(logging.Filter):
    """Add trace context to log records"""

    def filter(self, record):
        span = trace.get_current_span()
        if span:
            ctx = span.get_span_context()
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
            record.trace_flags = ctx.trace_flags
        else:
            record.trace_id = "00000000000000000000000000000000"
            record.span_id = "0000000000000000"
            record.trace_flags = "00"
        return True

# Configure logger
def setup_correlated_logging():
    handler = logging.StreamHandler()
    handler.addFilter(TraceContextFilter())

    # JSON formatter for structured logs
    formatter = logging.Formatter(
        json.dumps({
            "timestamp": "%(asctime)s",
            "level": "%(levelname)s",
            "message": "%(message)s",
            "logger": "%(name)s",
            "trace_id": "%(trace_id)s",
            "span_id": "%(span_id)s",
            "trace_flags": "%(trace_flags)s",
            "agent": os.getenv("AGENT_NAME", "unknown")
        })
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger("mcp_mesh")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    return logger

# Metrics with trace exemplars
class TracedMetrics:
    """Metrics that include trace exemplars"""

    def __init__(self, registry):
        self.request_counter = Counter(
            'mcp_mesh_requests_total',
            'Total requests with trace exemplars',
            ['agent', 'method', 'status'],
            registry=registry
        )

        self.request_histogram = Histogram(
            'mcp_mesh_request_duration_seconds',
            'Request duration with trace exemplars',
            ['agent', 'method'],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=registry
        )

    def record_request(self, agent: str, method: str,
                      duration: float, status: str = "success"):
        """Record metrics with trace context"""
        span = trace.get_current_span()

        # Get trace context for exemplar
        if span:
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, "032x")

            # Record with exemplar
            self.request_counter.labels(
                agent=agent,
                method=method,
                status=status
            ).inc(exemplar={'trace_id': trace_id})

            self.request_histogram.labels(
                agent=agent,
                method=method
            ).observe(duration, exemplar={'trace_id': trace_id})
        else:
            # Record without exemplar
            self.request_counter.labels(
                agent=agent,
                method=method,
                status=status
            ).inc()

            self.request_histogram.labels(
                agent=agent,
                method=method
            ).observe(duration)

# Correlated agent implementation
class CorrelatedAgent:
    def __init__(self, name: str):
        self.name = name
        self.tracer = trace.get_tracer(f"mcp-mesh-{name}")
        self.logger = setup_correlated_logging()
        self.metrics = TracedMetrics(REGISTRY)

    async def handle_request(self, request: dict):
        """Handle request with full observability"""
        start_time = time.time()

        with self.tracer.start_as_current_span(
            "handle_request",
            kind=trace.SpanKind.SERVER
        ) as span:
            # Log with trace context
            self.logger.info(
                f"Handling request",
                extra={
                    "request_id": request.get("id"),
                    "method": request.get("method"),
                    "agent": self.name
                }
            )

            try:
                # Process request
                result = await self._process(request)

                # Success metrics and logging
                duration = time.time() - start_time
                self.metrics.record_request(
                    agent=self.name,
                    method=request.get("method"),
                    duration=duration,
                    status="success"
                )

                self.logger.info(
                    f"Request completed successfully",
                    extra={
                        "duration_ms": duration * 1000,
                        "result_size": len(str(result))
                    }
                )

                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                # Error metrics and logging
                duration = time.time() - start_time
                self.metrics.record_request(
                    agent=self.name,
                    method=request.get("method"),
                    duration=duration,
                    status="error"
                )

                self.logger.error(
                    f"Request failed: {str(e)}",
                    extra={
                        "error_type": type(e).__name__,
                        "duration_ms": duration * 1000
                    },
                    exc_info=True
                )

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
```

### Step 6: Advanced Trace Analysis

Implement complex trace analysis queries:

```python
# trace_analysis.py
from jaeger_client import Config
import requests
from datetime import datetime, timedelta

class TraceAnalyzer:
    """Analyze traces from Jaeger"""

    def __init__(self, jaeger_url: str):
        self.jaeger_url = jaeger_url
        self.api_url = f"{jaeger_url}/api"

    def find_slow_traces(self, service: str,
                        lookback_hours: int = 1,
                        min_duration_ms: int = 1000):
        """Find traces slower than threshold"""

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=lookback_hours)

        params = {
            "service": service,
            "start": int(start_time.timestamp() * 1000000),
            "end": int(end_time.timestamp() * 1000000),
            "minDuration": f"{min_duration_ms}ms",
            "limit": 100
        }

        response = requests.get(
            f"{self.api_url}/traces",
            params=params
        )

        traces = response.json()["data"]

        # Analyze slow traces
        slow_operations = {}
        for trace in traces:
            for span in trace["spans"]:
                duration_ms = span["duration"] / 1000
                operation = span["operationName"]

                if operation not in slow_operations:
                    slow_operations[operation] = {
                        "count": 0,
                        "total_duration": 0,
                        "max_duration": 0,
                        "example_trace_id": None
                    }

                slow_operations[operation]["count"] += 1
                slow_operations[operation]["total_duration"] += duration_ms
                slow_operations[operation]["max_duration"] = max(
                    slow_operations[operation]["max_duration"],
                    duration_ms
                )

                if not slow_operations[operation]["example_trace_id"]:
                    slow_operations[operation]["example_trace_id"] = trace["traceID"]

        return slow_operations

    def find_error_patterns(self, service: str, lookback_hours: int = 1):
        """Find common error patterns in traces"""

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=lookback_hours)

        params = {
            "service": service,
            "start": int(start_time.timestamp() * 1000000),
            "end": int(end_time.timestamp() * 1000000),
            "tags": '{"error":"true"}',
            "limit": 200
        }

        response = requests.get(
            f"{self.api_url}/traces",
            params=params
        )

        traces = response.json()["data"]

        # Analyze error patterns
        error_patterns = {}
        for trace in traces:
            for span in trace["spans"]:
                if any(tag["key"] == "error" and tag["value"]
                      for tag in span.get("tags", [])):

                    # Extract error details
                    error_msg = next(
                        (tag["value"] for tag in span["tags"]
                         if tag["key"] == "error.message"),
                        "Unknown error"
                    )

                    pattern_key = f"{span['operationName']}:{error_msg[:50]}"

                    if pattern_key not in error_patterns:
                        error_patterns[pattern_key] = {
                            "count": 0,
                            "operations": set(),
                            "example_trace_id": trace["traceID"],
                            "first_seen": datetime.fromtimestamp(
                                span["startTime"] / 1000000
                            ),
                            "last_seen": datetime.fromtimestamp(
                                span["startTime"] / 1000000
                            )
                        }

                    error_patterns[pattern_key]["count"] += 1
                    error_patterns[pattern_key]["operations"].add(
                        span["operationName"]
                    )
                    error_patterns[pattern_key]["last_seen"] = datetime.fromtimestamp(
                        span["startTime"] / 1000000
                    )

        return error_patterns

    def calculate_service_dependencies(self, service: str,
                                     lookback_hours: int = 1):
        """Calculate service dependency metrics"""

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=lookback_hours)

        response = requests.get(
            f"{self.api_url}/dependencies",
            params={
                "endTs": int(end_time.timestamp() * 1000),
                "lookback": int(lookback_hours * 3600 * 1000)
            }
        )

        dependencies = response.json()["data"]

        # Filter for our service
        service_deps = {
            "upstream": [],
            "downstream": []
        }

        for dep in dependencies:
            if dep["parent"] == service:
                service_deps["downstream"].append({
                    "service": dep["child"],
                    "call_count": dep["callCount"],
                    "error_count": dep.get("errorCount", 0),
                    "error_rate": dep.get("errorCount", 0) / dep["callCount"]
                                 if dep["callCount"] > 0 else 0
                })
            elif dep["child"] == service:
                service_deps["upstream"].append({
                    "service": dep["parent"],
                    "call_count": dep["callCount"],
                    "error_count": dep.get("errorCount", 0),
                    "error_rate": dep.get("errorCount", 0) / dep["callCount"]
                                 if dep["callCount"] > 0 else 0
                })

        return service_deps

# Usage example
analyzer = TraceAnalyzer("http://jaeger.mcp-mesh.local")

# Find slow operations
slow_ops = analyzer.find_slow_traces("mcp-mesh-registry", min_duration_ms=500)
for op, stats in slow_ops.items():
    print(f"Operation: {op}")
    print(f"  Count: {stats['count']}")
    print(f"  Avg Duration: {stats['total_duration']/stats['count']:.2f}ms")
    print(f"  Max Duration: {stats['max_duration']:.2f}ms")
    print(f"  Example: {stats['example_trace_id']}")

# Find error patterns
errors = analyzer.find_error_patterns("mcp-mesh-weather-agent")
for pattern, info in errors.items():
    print(f"Error Pattern: {pattern}")
    print(f"  Count: {info['count']}")
    print(f"  Duration: {info['first_seen']} - {info['last_seen']}")
```

## Configuration Options

| Component        | Configuration | Purpose                |
| ---------------- | ------------- | ---------------------- |
| Sampling Rate    | `0.1-100%`    | Control trace volume   |
| Retention        | `7 days`      | Trace storage duration |
| Collector Memory | `2Gi`         | Processing capacity    |
| Span Batch Size  | `1024`        | Export efficiency      |
| Tail Sampling    | Various       | Smart sampling         |

## Examples

### Example 1: Custom Span Attributes

```python
# custom_attributes.py
@trace_async("weather.forecast")
async def get_weather_forecast(location: str, days: int = 7):
    """Get weather forecast with rich span attributes"""
    span = trace.get_current_span()

    # Add semantic conventions
    span.set_attribute("weather.location", location)
    span.set_attribute("weather.forecast_days", days)
    span.set_attribute("weather.coordinates.lat", 40.7128)
    span.set_attribute("weather.coordinates.lon", -74.0060)

    # Add custom business attributes
    span.set_attribute("customer.tier", "premium")
    span.set_attribute("api.version", "v2")
    span.set_attribute("cache.hit", False)

    # Add events during execution
    span.add_event("cache_miss", {"key": f"forecast_{location}_{days}"})

    # External API call with baggage
    with trace.use_span(span, end_on_exit=False):
        baggage.set_baggage("customer.id", "12345")
        baggage.set_baggage("request.priority", "high")

        result = await call_weather_api(location, days)

    span.add_event("api_response_received", {
        "response.size": len(str(result)),
        "response.cached": False
    })

    return result
```

### Example 2: Distributed Transaction Tracing

```python
# distributed_transaction.py
class DistributedTransaction:
    """Trace complex multi-agent transactions"""

    def __init__(self):
        self.tracer = trace.get_tracer("mcp-mesh-transaction")

    async def process_order(self, order: dict):
        """Process order across multiple agents"""

        with self.tracer.start_as_current_span(
            "process_order",
            kind=trace.SpanKind.SERVER,
            attributes={
                "order.id": order["id"],
                "order.total": order["total"],
                "order.items_count": len(order["items"])
            }
        ) as span:

            # Step 1: Validate order
            with self.tracer.start_as_current_span("validate_order"):
                validation_result = await self.validate_with_inventory(order)
                if not validation_result["valid"]:
                    span.set_status(Status(StatusCode.ERROR, "Invalid order"))
                    return {"status": "failed", "reason": "validation"}

            # Step 2: Process payment
            with self.tracer.start_as_current_span(
                "process_payment",
                kind=trace.SpanKind.CLIENT
            ) as payment_span:
                payment_span.set_attribute("payment.amount", order["total"])
                payment_span.set_attribute("payment.currency", "USD")

                try:
                    payment_result = await self.call_payment_agent(order)
                    payment_span.set_attribute(
                        "payment.transaction_id",
                        payment_result["transaction_id"]
                    )
                except Exception as e:
                    payment_span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "Payment failed"))
                    raise

            # Step 3: Update inventory
            with self.tracer.start_as_current_span("update_inventory"):
                inventory_result = await self.update_inventory_agent(order)

            # Step 4: Send notification
            with self.tracer.start_as_current_span(
                "send_notification",
                kind=trace.SpanKind.PRODUCER
            ) as notif_span:
                notif_span.set_attribute("notification.type", "order_complete")
                await self.notify_customer(order)

            span.set_status(Status(StatusCode.OK))
            return {
                "status": "completed",
                "transaction_id": payment_result["transaction_id"]
            }
```

## Best Practices

1. **Semantic Conventions**: Follow OpenTelemetry standards
2. **Sampling Strategy**: Balance visibility with cost
3. **Attribute Limits**: Keep cardinality reasonable
4. **Context Propagation**: Always propagate trace context
5. **Error Handling**: Record exceptions in spans

## Common Pitfalls

### Pitfall 1: Trace Context Lost

**Problem**: Traces broken across async boundaries

**Solution**: Properly propagate context:

```python
# Preserve context across async operations
import contextvars

trace_context = contextvars.ContextVar('trace_context')

async def async_operation():
    # Get current context
    ctx = trace_context.get()

    # Create new task with context
    async def task_with_context():
        trace_context.set(ctx)
        with tracer.start_as_current_span("async_task"):
            await do_work()

    await asyncio.create_task(task_with_context())
```

### Pitfall 2: Too Many Spans

**Problem**: Creating spans for every function call

**Solution**: Focus on meaningful operations:

```python
# Bad - too granular
def add(a, b):
    with tracer.start_as_current_span("add"):
        return a + b

# Good - meaningful operations
async def process_order(order):
    with tracer.start_as_current_span("process_order"):
        # Multiple operations within one span
        validated = await validate_order(order)
        payment = await process_payment(order)
        await update_inventory(order)
```

## Testing

### Test Trace Instrumentation

```python
# test_tracing.py
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

@pytest.fixture
def trace_exporter():
    """Set up in-memory trace exporter for testing"""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    yield exporter

    # Cleanup
    exporter.clear()

def test_agent_tracing(trace_exporter):
    """Test that agent creates proper spans"""
    agent = TracedMCPAgent("test-agent")

    # Execute traced operation
    await agent.handle_request({"method": "test", "id": "123"})

    # Get spans
    spans = trace_exporter.get_finished_spans()

    # Verify spans
    assert len(spans) > 0

    # Check main span
    main_span = next(s for s in spans if s.name == "agent.handle_request")
    assert main_span.attributes["agent.name"] == "test-agent"
    assert main_span.attributes["request.method"] == "test"
    assert main_span.status.status_code == StatusCode.OK

    # Check child spans exist
    child_spans = [s for s in spans if s.parent == main_span.context]
    assert len(child_spans) > 0
```

### Load Test Tracing

```bash
#!/bin/bash
# load-test-tracing.sh

echo "Load testing trace collection..."

# Generate load
for i in {1..1000}; do
  curl -X POST http://localhost:8080/api/trace-test \
    -H "Content-Type: application/json" \
    -d '{"test_id": "'$i'"}' &
done
wait

# Check collector metrics
curl -s http://localhost:8888/metrics | grep -E "otelcol_receiver_accepted_spans|otelcol_exporter_sent_spans"

# Query Jaeger for traces
curl -s "http://localhost:16686/api/traces?service=mcp-mesh-registry&limit=10" | \
  jq '.data[].spans | length'
```

## Monitoring and Debugging

### Monitor Tracing Pipeline

```yaml
# tracing-monitoring.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tracing-alerts
  namespace: observability
data:
  alerts.yaml: |
    groups:
    - name: tracing
      rules:
      - alert: HighTraceDropRate
        expr: |
          rate(otelcol_processor_dropped_spans[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High trace drop rate"
          description: "Dropping {{ $value | humanize }} spans/sec"

      - alert: TracingCollectorDown
        expr: up{job="opentelemetry-collector"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "OpenTelemetry collector is down"

      - alert: JaegerStorageFull
        expr: |
          elasticsearch_filesystem_data_available_bytes /
          elasticsearch_filesystem_data_size_bytes < 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Jaeger storage almost full"
```

### Debug Missing Traces

```bash
# Check if spans are being created
kubectl logs -n mcp-mesh deployment/weather-agent | grep -i trace

# Verify OTEL collector is receiving spans
kubectl logs -n observability deployment/otel-collector | grep -i "spans received"

# Check Jaeger ingestion
kubectl port-forward -n observability svc/mcp-mesh-jaeger-query 16686
# Visit http://localhost:16686 and search for service

# Test trace propagation
curl -X POST http://localhost:8080/test \
  -H "traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" \
  -v

# Check for the trace
curl "http://localhost:16686/api/traces/0af7651916cd43dd8448eb211c80319c"
```

## 🔧 Troubleshooting

### Issue 1: Traces Not Appearing

**Symptoms**: No traces in Jaeger UI

**Cause**: Exporter misconfiguration or network issues

**Solution**:

```python
# Enable debug logging
import logging
logging.getLogger("opentelemetry").setLevel(logging.DEBUG)

# Test exporter connection
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

exporter = OTLPSpanExporter(
    endpoint="otel-collector:4317",
    insecure=True,
)

# Try to export a test span
test_span = create_test_span()
result = exporter.export([test_span])
print(f"Export result: {result}")
```

### Issue 2: Incomplete Traces

**Symptoms**: Traces missing spans or broken

**Cause**: Context not propagated correctly

**Solution**:

```python
# Ensure context propagation in async code
from opentelemetry import context

async def parent_operation():
    with tracer.start_as_current_span("parent") as span:
        # Capture context
        ctx = context.get_current()

        # Pass to async task
        await asyncio.create_task(child_operation(ctx))

async def child_operation(parent_context):
    # Attach parent context
    context.attach(parent_context)

    with tracer.start_as_current_span("child") as span:
        # This span will be properly linked
        await do_work()
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Trace Size**: Large traces may be truncated
- **Storage Cost**: Traces consume significant storage
- **Sampling Trade-offs**: 100% sampling not feasible
- **Clock Skew**: Can cause trace visualization issues

## 📝 TODO

- [ ] Add trace analytics with Apache Spark
- [ ] Implement anomaly detection on traces
- [ ] Create trace-based testing framework
- [ ] Add support for continuous profiling
- [ ] Document eBPF-based tracing

## Summary

You now have distributed tracing implemented:

Key takeaways:

- 🔑 End-to-end visibility across agents
- 🔑 Correlation with metrics and logs
- 🔑 Smart sampling strategies
- 🔑 Performance analysis capabilities

## Next Steps

Let's add centralized logging to complete observability.

Continue to [Centralized Logging](./04-centralized-logging.md) →

---

💡 **Tip**: Use trace exemplars in Grafana to jump from metrics to traces: Enable with `--enable-feature=exemplar-storage`

📚 **Reference**: [OpenTelemetry Documentation](https://opentelemetry.io/docs/)

🧪 **Try It**: Create a custom span processor to enrich traces with business metadata

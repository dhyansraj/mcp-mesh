# Centralized Logging

> Aggregate, search, and analyze logs from all MCP Mesh components in one place

## Overview

Centralized logging is essential for troubleshooting and monitoring distributed MCP Mesh deployments. This guide covers implementing the ELK stack (Elasticsearch, Logstash/Fluentd, Kibana) for log aggregation, configuring structured logging in agents, creating powerful search queries, and building log-based dashboards. You'll learn to correlate logs with traces and metrics for comprehensive observability.

Effective centralized logging enables quick problem resolution, security monitoring, and operational insights across your entire MCP Mesh system.

## Key Concepts

- **Log Aggregation**: Collecting logs from all sources
- **Structured Logging**: JSON-formatted logs with metadata
- **Log Parsing**: Extracting fields from log messages
- **Index Management**: Lifecycle policies for log retention
- **Correlation**: Linking logs with traces and metrics

## Step-by-Step Guide

### Step 1: Deploy the ELK Stack

Set up Elasticsearch, Logstash/Fluentd, and Kibana:

```bash
# Add Elastic Helm repository
helm repo add elastic https://helm.elastic.co
helm repo update

# Create namespace
kubectl create namespace logging

# Deploy Elasticsearch
cat > elasticsearch-values.yaml << 'EOF'
clusterName: "mcp-mesh-logs"
nodeGroup: "master"

replicas: 3
minimumMasterNodes: 2

resources:
  requests:
    cpu: "1000m"
    memory: "2Gi"
  limits:
    cpu: "2000m"
    memory: "4Gi"

volumeClaimTemplate:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 100Gi
  storageClassName: fast-ssd

esConfig:
  elasticsearch.yml: |
    cluster.name: "mcp-mesh-logs"
    network.host: 0.0.0.0
    discovery.seed_hosts: ["elasticsearch-master-0", "elasticsearch-master-1", "elasticsearch-master-2"]
    cluster.initial_master_nodes: ["elasticsearch-master-0", "elasticsearch-master-1", "elasticsearch-master-2"]
    xpack.security.enabled: true
    xpack.security.transport.ssl.enabled: true
    xpack.security.transport.ssl.verification_mode: certificate
    xpack.security.transport.ssl.keystore.path: /usr/share/elasticsearch/config/certs/elastic-certificates.p12
    xpack.security.transport.ssl.truststore.path: /usr/share/elasticsearch/config/certs/elastic-certificates.p12
    xpack.monitoring.collection.enabled: true

extraEnvs:
  - name: ELASTIC_PASSWORD
    valueFrom:
      secretKeyRef:
        name: elastic-credentials
        key: password

persistence:
  enabled: true
  labels:
    enabled: true

antiAffinity: "hard"

# Lifecycle policy for log rotation
lifecycle:
  enabled: true
  policies:
    mcp_mesh_logs:
      phases:
        hot:
          min_age: "0ms"
          actions:
            rollover:
              max_age: "1d"
              max_size: "50gb"
            set_priority:
              priority: 100
        warm:
          min_age: "2d"
          actions:
            shrink:
              number_of_shards: 1
            forcemerge:
              max_num_segments: 1
            set_priority:
              priority: 50
        cold:
          min_age: "7d"
          actions:
            set_priority:
              priority: 0
        delete:
          min_age: "30d"
          actions:
            delete: {}
EOF

# Create credentials secret
kubectl create secret generic elastic-credentials \
  --from-literal=password=changeme \
  -n logging

# Install Elasticsearch
helm install elasticsearch elastic/elasticsearch \
  --namespace logging \
  --values elasticsearch-values.yaml

# Deploy Kibana
cat > kibana-values.yaml << 'EOF'
elasticsearchHosts: "http://elasticsearch-master:9200"

replicas: 2

resources:
  requests:
    cpu: "500m"
    memory: "1Gi"
  limits:
    cpu: "1000m"
    memory: "2Gi"

kibanaConfig:
  kibana.yml: |
    server.name: kibana
    server.host: "0"
    elasticsearch.hosts: ["http://elasticsearch-master:9200"]
    elasticsearch.username: "elastic"
    elasticsearch.password: "${ELASTIC_PASSWORD}"
    xpack.monitoring.ui.container.elasticsearch.enabled: true
    logging.json: true

extraEnvs:
  - name: ELASTIC_PASSWORD
    valueFrom:
      secretKeyRef:
        name: elastic-credentials
        key: password

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: kibana.mcp-mesh.local
      paths:
        - path: /
          pathType: Prefix

service:
  type: ClusterIP
  port: 5601
EOF

# Install Kibana
helm install kibana elastic/kibana \
  --namespace logging \
  --values kibana-values.yaml

# Deploy Fluentd for log collection
cat > fluentd-values.yaml << 'EOF'
image:
  repository: fluent/fluentd-kubernetes-daemonset
  tag: v1.16-debian-elasticsearch7-1

elasticsearch:
  host: elasticsearch-master
  port: 9200
  scheme: http
  user: elastic
  password: changeme

rbac:
  create: true

resources:
  limits:
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 200Mi

# Fluentd configuration
configMaps:
  useDefaults:
    systemdConf: false
    containersInputConf: true
    systemInputConf: false
    forwardInputConf: false
    monitoringConf: true
    outputConf: false

fileConfigs:
  01_sources.conf: |
    <source>
      @type tail
      @id in_tail_container_logs
      path /var/log/containers/*mcp-mesh*.log
      pos_file /var/log/fluentd-containers.log.pos
      tag kubernetes.*
      exclude_path ["/var/log/containers/*fluentd*"]
      read_from_head true
      <parse>
        @type multi_format
        <pattern>
          format json
          time_key timestamp
          time_format %Y-%m-%dT%H:%M:%S.%NZ
        </pattern>
        <pattern>
          format /^(?<time>.+) (?<stream>stdout|stderr) [^ ]* (?<log>.*)$/
          time_format %Y-%m-%dT%H:%M:%S.%N%:z
        </pattern>
      </parse>
    </source>

  02_filters.conf: |
    <filter kubernetes.**>
      @type kubernetes_metadata
      @id filter_kube_metadata
      kubernetes_url "#{ENV['KUBERNETES_URL']}"
      verify_ssl "#{ENV['KUBERNETES_VERIFY_SSL']}"
      ca_file "#{ENV['KUBERNETES_CA_FILE']}"
      skip_labels false
      skip_container_metadata false
      skip_master_url false
      skip_namespace_metadata false
    </filter>

    <filter kubernetes.**>
      @type parser
      @id filter_parser
      key_name log
      reserve_data true
      remove_key_name_field true
      <parse>
        @type multi_format
        <pattern>
          format json
        </pattern>
        <pattern>
          format none
        </pattern>
      </parse>
    </filter>

    <filter kubernetes.**>
      @type record_transformer
      @id filter_records
      <record>
        hostname ${hostname}
        environment "#{ENV['ENVIRONMENT'] || 'development'}"
        cluster_name "#{ENV['CLUSTER_NAME'] || 'mcp-mesh'}"
      </record>
    </filter>

  03_outputs.conf: |
    <match kubernetes.**>
      @type elasticsearch
      @id out_es
      @log_level info
      include_tag_key true
      host "#{ENV['FLUENT_ELASTICSEARCH_HOST']}"
      port "#{ENV['FLUENT_ELASTICSEARCH_PORT']}"
      scheme "#{ENV['FLUENT_ELASTICSEARCH_SCHEME'] || 'http'}"
      ssl_verify "#{ENV['FLUENT_ELASTICSEARCH_SSL_VERIFY'] || 'true'}"
      ssl_version "#{ENV['FLUENT_ELASTICSEARCH_SSL_VERSION'] || 'TLSv1_2'}"
      user "#{ENV['FLUENT_ELASTICSEARCH_USER'] || 'elastic'}"
      password "#{ENV['FLUENT_ELASTICSEARCH_PASSWORD']}"
      reload_connections false
      reconnect_on_error true
      reload_on_failure true
      log_es_400_reason true
      logstash_prefix mcp-mesh-logs
      logstash_dateformat %Y.%m.%d
      include_timestamp true
      template_name mcp-mesh-logs
      template_file /fluentd/etc/elasticsearch-template.json
      template_overwrite true
      <buffer>
        flush_thread_count 8
        flush_interval 5s
        chunk_limit_size 2M
        queue_limit_length 32
        retry_max_interval 30
        retry_forever true
      </buffer>
    </match>

tolerations:
  - key: node-role.kubernetes.io/master
    operator: Exists
    effect: NoSchedule
EOF

# Install Fluentd
helm install fluentd bitnami/fluentd \
  --namespace logging \
  --values fluentd-values.yaml
```

### Step 2: Configure Structured Logging in MCP Mesh

Implement structured logging in agents:

```python
# mcp_mesh/logging.py
import logging
import json
import sys
import os
from datetime import datetime
from pythonjsonlogger import jsonlogger
from opentelemetry import trace
import asyncio
from contextvars import ContextVar

# Context variables for request tracking
request_id_var: ContextVar[str] = ContextVar('request_id', default='')
user_id_var: ContextVar[str] = ContextVar('user_id', default='')

class MCPMeshLogFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter for MCP Mesh logs"""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)

        # Add timestamp
        log_record['timestamp'] = datetime.utcnow().isoformat() + 'Z'

        # Add log level
        log_record['level'] = record.levelname

        # Add service information
        log_record['service'] = {
            'name': os.getenv('SERVICE_NAME', 'unknown'),
            'version': os.getenv('SERVICE_VERSION', '1.0.0'),
            'environment': os.getenv('ENVIRONMENT', 'development'),
            'instance_id': os.getenv('HOSTNAME', 'unknown')
        }

        # Add Kubernetes metadata
        log_record['kubernetes'] = {
            'namespace': os.getenv('K8S_NAMESPACE', 'default'),
            'pod_name': os.getenv('HOSTNAME', 'unknown'),
            'node_name': os.getenv('NODE_NAME', 'unknown')
        }

        # Add trace context
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            ctx = span.get_span_context()
            log_record['trace'] = {
                'trace_id': format(ctx.trace_id, '032x'),
                'span_id': format(ctx.span_id, '016x'),
                'trace_flags': format(ctx.trace_flags, '02x')
            }

        # Add request context
        request_id = request_id_var.get()
        if request_id:
            log_record['request_id'] = request_id

        user_id = user_id_var.get()
        if user_id:
            log_record['user_id'] = user_id

        # Add source location
        log_record['source'] = {
            'file': record.pathname,
            'line': record.lineno,
            'function': record.funcName
        }

        # Move message to correct field
        if 'message' in log_record:
            log_record['msg'] = log_record.pop('message')

def setup_logging(service_name: str, log_level: str = "INFO"):
    """Set up structured logging for MCP Mesh service"""

    # Create logger
    logger = logging.getLogger('mcp_mesh')
    logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    logger.handlers = []

    # Create console handler with JSON formatter
    handler = logging.StreamHandler(sys.stdout)
    formatter = MCPMeshLogFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Add exception hook for unhandled exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
            extra={
                'exception_type': exc_type.__name__,
                'exception_message': str(exc_value)
            }
        )

    sys.excepthook = handle_exception

    return logger

# Logging utilities
class LogContext:
    """Context manager for adding fields to logs"""

    def __init__(self, **kwargs):
        self.fields = kwargs
        self.tokens = []

    def __enter__(self):
        # Set context variables
        if 'request_id' in self.fields:
            self.tokens.append(request_id_var.set(self.fields['request_id']))
        if 'user_id' in self.fields:
            self.tokens.append(user_id_var.set(self.fields['user_id']))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Reset context variables
        for token in self.tokens:
            request_id_var.reset(token)

# Enhanced logger for agents
class AgentLogger:
    """Agent-specific logger with additional functionality"""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.logger = setup_logging(f"mcp-mesh-{agent_name}")
        self._metrics = {
            'requests_total': 0,
            'errors_total': 0,
            'warnings_total': 0
        }

    def _log(self, level: str, message: str, **kwargs):
        """Internal log method with agent context"""
        extra = {
            'agent': {
                'name': self.agent_name,
                'type': 'mcp-mesh'
            }
        }
        extra.update(kwargs)

        # Update metrics
        if level == 'ERROR':
            self._metrics['errors_total'] += 1
        elif level == 'WARNING':
            self._metrics['warnings_total'] += 1

        getattr(self.logger, level.lower())(message, extra=extra)

    def info(self, message: str, **kwargs):
        self._log('INFO', message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log('WARNING', message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log('ERROR', message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._log('DEBUG', message, **kwargs)

    def request(self, method: str, params: dict = None,
               duration_ms: float = None, status: str = "success"):
        """Log API request with standard fields"""
        self._metrics['requests_total'] += 1

        self.info(
            f"Request processed: {method}",
            request={
                'method': method,
                'params': params or {},
                'duration_ms': duration_ms,
                'status': status
            },
            metrics={
                'duration_ms': duration_ms
            }
        )

    def exception(self, message: str, exc: Exception, **kwargs):
        """Log exception with full context"""
        import traceback

        self.error(
            message,
            exception={
                'type': type(exc).__name__,
                'message': str(exc),
                'traceback': traceback.format_exc()
            },
            **kwargs
        )

    def audit(self, action: str, resource: str, result: str, **kwargs):
        """Log audit event"""
        self.info(
            f"Audit: {action} {resource}",
            audit={
                'action': action,
                'resource': resource,
                'result': result,
                'timestamp': datetime.utcnow().isoformat()
            },
            **kwargs
        )

# Example usage in an agent
class LoggedWeatherAgent:
    def __init__(self):
        self.logger = AgentLogger("weather-agent")
        self.cache = {}

    async def get_forecast(self, location: str, days: int = 7):
        """Get weather forecast with comprehensive logging"""
        start_time = asyncio.get_event_loop().time()

        # Create request context
        request_id = f"req-{start_time}"

        with LogContext(request_id=request_id):
            self.logger.info(
                f"Getting forecast for {location}",
                location=location,
                days=days,
                cache_keys=list(self.cache.keys())
            )

            try:
                # Check cache
                cache_key = f"{location}:{days}"
                if cache_key in self.cache:
                    self.logger.debug(
                        "Cache hit",
                        cache_key=cache_key,
                        cache_size=len(self.cache)
                    )
                    return self.cache[cache_key]

                # Call external API
                self.logger.info(
                    "Calling weather API",
                    api_endpoint="https://api.weather.com/forecast",
                    timeout=30
                )

                # Simulate API call
                await asyncio.sleep(0.1)
                result = {"temp": 72, "conditions": "sunny"}

                # Cache result
                self.cache[cache_key] = result

                # Calculate duration
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

                # Log successful request
                self.logger.request(
                    method="get_forecast",
                    params={"location": location, "days": days},
                    duration_ms=duration_ms,
                    status="success"
                )

                # Audit log
                self.logger.audit(
                    action="forecast_retrieved",
                    resource=f"location:{location}",
                    result="success",
                    user_id="api-user-123"
                )

                return result

            except Exception as e:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

                self.logger.exception(
                    f"Failed to get forecast for {location}",
                    exc=e,
                    location=location,
                    duration_ms=duration_ms
                )

                self.logger.request(
                    method="get_forecast",
                    params={"location": location, "days": days},
                    duration_ms=duration_ms,
                    status="error"
                )

                raise
```

### Step 3: Create Elasticsearch Index Templates

Define index templates for optimal log storage:

```json
// elasticsearch-template.json
{
  "index_patterns": ["mcp-mesh-logs-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "index.lifecycle.name": "mcp-mesh-logs",
      "index.lifecycle.rollover_alias": "mcp-mesh-logs",
      "analysis": {
        "analyzer": {
          "log_analyzer": {
            "type": "custom",
            "tokenizer": "standard",
            "filter": ["lowercase", "stop", "snowball"]
          }
        }
      }
    },
    "mappings": {
      "properties": {
        "timestamp": {
          "type": "date",
          "format": "strict_date_time"
        },
        "level": {
          "type": "keyword"
        },
        "msg": {
          "type": "text",
          "analyzer": "log_analyzer",
          "fields": {
            "keyword": {
              "type": "keyword",
              "ignore_above": 256
            }
          }
        },
        "service": {
          "properties": {
            "name": { "type": "keyword" },
            "version": { "type": "keyword" },
            "environment": { "type": "keyword" },
            "instance_id": { "type": "keyword" }
          }
        },
        "kubernetes": {
          "properties": {
            "namespace": { "type": "keyword" },
            "pod_name": { "type": "keyword" },
            "node_name": { "type": "keyword" },
            "container_name": { "type": "keyword" },
            "labels": { "type": "object" }
          }
        },
        "trace": {
          "properties": {
            "trace_id": { "type": "keyword" },
            "span_id": { "type": "keyword" },
            "trace_flags": { "type": "keyword" }
          }
        },
        "request": {
          "properties": {
            "method": { "type": "keyword" },
            "params": { "type": "object" },
            "duration_ms": { "type": "float" },
            "status": { "type": "keyword" }
          }
        },
        "exception": {
          "properties": {
            "type": { "type": "keyword" },
            "message": { "type": "text" },
            "traceback": { "type": "text" }
          }
        },
        "audit": {
          "properties": {
            "action": { "type": "keyword" },
            "resource": { "type": "keyword" },
            "result": { "type": "keyword" },
            "user_id": { "type": "keyword" }
          }
        },
        "metrics": {
          "properties": {
            "duration_ms": { "type": "float" },
            "count": { "type": "long" },
            "size_bytes": { "type": "long" }
          }
        },
        "agent": {
          "properties": {
            "name": { "type": "keyword" },
            "type": { "type": "keyword" }
          }
        },
        "source": {
          "properties": {
            "file": { "type": "keyword" },
            "line": { "type": "long" },
            "function": { "type": "keyword" }
          }
        }
      }
    }
  },
  "composed_of": ["mcp-mesh-logs-settings", "mcp-mesh-logs-mappings"],
  "priority": 200,
  "version": 1,
  "_meta": {
    "description": "Template for MCP Mesh application logs"
  }
}
```

Apply the template:

```bash
# Create index template
curl -X PUT "http://localhost:9200/_index_template/mcp-mesh-logs" \
  -H "Content-Type: application/json" \
  -u elastic:changeme \
  -d @elasticsearch-template.json

# Create initial index with alias
curl -X PUT "http://localhost:9200/mcp-mesh-logs-000001" \
  -H "Content-Type: application/json" \
  -u elastic:changeme \
  -d '{
    "aliases": {
      "mcp-mesh-logs": {
        "is_write_index": true
      }
    }
  }'
```

### Step 4: Build Kibana Dashboards

Create saved searches and visualizations:

```json
// kibana-dashboard.json
{
  "version": "8.11.0",
  "objects": [
    {
      "id": "mcp-mesh-logs-search",
      "type": "search",
      "attributes": {
        "title": "MCP Mesh Logs",
        "columns": ["timestamp", "level", "service.name", "msg"],
        "sort": [["timestamp", "desc"]],
        "kibanaSavedObjectMeta": {
          "searchSourceJSON": {
            "index": "mcp-mesh-logs-*",
            "query": {
              "match_all": {}
            },
            "filter": []
          }
        }
      }
    },
    {
      "id": "mcp-mesh-error-timeline",
      "type": "visualization",
      "attributes": {
        "title": "Error Timeline",
        "visState": {
          "type": "line",
          "params": {
            "grid": { "categoryLines": false, "style": { "color": "#eee" } },
            "categoryAxes": [
              {
                "id": "CategoryAxis-1",
                "type": "category",
                "position": "bottom",
                "show": true,
                "style": {},
                "scale": { "type": "linear" },
                "labels": { "show": true, "filter": true, "truncate": 100 },
                "title": {}
              }
            ],
            "valueAxes": [
              {
                "id": "ValueAxis-1",
                "name": "LeftAxis-1",
                "type": "value",
                "position": "left",
                "show": true,
                "style": {},
                "scale": { "type": "linear", "mode": "normal" },
                "labels": {
                  "show": true,
                  "rotate": 0,
                  "filter": false,
                  "truncate": 100
                },
                "title": { "text": "Error Count" }
              }
            ],
            "seriesParams": [
              {
                "show": true,
                "type": "line",
                "mode": "normal",
                "data": { "label": "Error Count", "id": "1" },
                "valueAxis": "ValueAxis-1",
                "drawLinesBetweenPoints": true,
                "showCircles": true
              }
            ],
            "addTooltip": true,
            "addLegend": true,
            "legendPosition": "right",
            "times": [],
            "addTimeMarker": false
          },
          "aggs": [
            {
              "id": "1",
              "enabled": true,
              "type": "count",
              "schema": "metric",
              "params": {}
            },
            {
              "id": "2",
              "enabled": true,
              "type": "date_histogram",
              "schema": "segment",
              "params": {
                "field": "timestamp",
                "interval": "auto",
                "customInterval": "2h",
                "min_doc_count": 1,
                "extended_bounds": {}
              }
            },
            {
              "id": "3",
              "enabled": true,
              "type": "filters",
              "schema": "group",
              "params": {
                "filters": [
                  { "input": { "query": "level:ERROR" }, "label": "Errors" },
                  { "input": { "query": "level:WARNING" }, "label": "Warnings" }
                ]
              }
            }
          ]
        },
        "kibanaSavedObjectMeta": {
          "searchSourceJSON": {
            "index": "mcp-mesh-logs-*",
            "query": { "match_all": {} },
            "filter": []
          }
        }
      }
    },
    {
      "id": "mcp-mesh-agent-logs",
      "type": "lens",
      "attributes": {
        "title": "Logs by Agent",
        "state": {
          "datasourceStates": {
            "indexpattern": {
              "layers": {
                "layer1": {
                  "columns": {
                    "col1": {
                      "label": "Count",
                      "dataType": "number",
                      "operationType": "count",
                      "sourceField": "Records"
                    },
                    "col2": {
                      "label": "Agent",
                      "dataType": "string",
                      "operationType": "terms",
                      "sourceField": "agent.name",
                      "params": {
                        "size": 10,
                        "orderBy": { "type": "column", "columnId": "col1" },
                        "orderDirection": "desc"
                      }
                    },
                    "col3": {
                      "label": "Level",
                      "dataType": "string",
                      "operationType": "terms",
                      "sourceField": "level",
                      "params": {
                        "size": 5,
                        "orderBy": { "type": "alphabetical" },
                        "orderDirection": "asc"
                      }
                    }
                  }
                }
              }
            }
          },
          "visualization": {
            "legend": { "isVisible": true, "position": "right" },
            "valueLabels": "hide",
            "fittingFunction": "None",
            "axisTitlesVisibilitySettings": {
              "x": true,
              "yLeft": true,
              "yRight": true
            },
            "gridlinesVisibilitySettings": {
              "x": true,
              "yLeft": true,
              "yRight": true
            },
            "preferredSeriesType": "bar_stacked",
            "layers": [
              {
                "layerId": "layer1",
                "seriesType": "bar_stacked",
                "xAccessor": "col2",
                "accessors": ["col1"],
                "splitAccessor": "col3"
              }
            ]
          }
        }
      }
    },
    {
      "id": "mcp-mesh-log-dashboard",
      "type": "dashboard",
      "attributes": {
        "title": "MCP Mesh Log Analysis",
        "hits": 0,
        "description": "Comprehensive log analysis for MCP Mesh",
        "panelsJSON": "[{\"version\":\"8.11.0\",\"type\":\"visualization\",\"gridData\":{\"x\":0,\"y\":0,\"w\":48,\"h\":15,\"i\":\"1\"},\"panelIndex\":\"1\",\"embeddableConfig\":{\"enhancements\":{}},\"panelRefName\":\"panel_1\"},{\"version\":\"8.11.0\",\"type\":\"lens\",\"gridData\":{\"x\":0,\"y\":15,\"w\":24,\"h\":15,\"i\":\"2\"},\"panelIndex\":\"2\",\"embeddableConfig\":{\"enhancements\":{}},\"panelRefName\":\"panel_2\"},{\"version\":\"8.11.0\",\"type\":\"search\",\"gridData\":{\"x\":24,\"y\":15,\"w\":24,\"h\":30,\"i\":\"3\"},\"panelIndex\":\"3\",\"embeddableConfig\":{\"enhancements\":{}},\"panelRefName\":\"panel_3\"}]",
        "optionsJSON": "{\"useMargins\":true,\"syncColors\":false,\"hidePanelTitles\":false}",
        "timeRestore": true,
        "timeTo": "now",
        "timeFrom": "now-24h",
        "refreshInterval": { "pause": false, "value": 30000 },
        "kibanaSavedObjectMeta": {
          "searchSourceJSON": "{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[]}"
        }
      },
      "references": [
        {
          "id": "mcp-mesh-error-timeline",
          "name": "panel_1",
          "type": "visualization"
        },
        { "id": "mcp-mesh-agent-logs", "name": "panel_2", "type": "lens" },
        { "id": "mcp-mesh-logs-search", "name": "panel_3", "type": "search" }
      ]
    }
  ]
}
```

### Step 5: Implement Log Analysis Queries

Create powerful log analysis queries:

```python
# log_analysis.py
from elasticsearch import Elasticsearch
from datetime import datetime, timedelta
import json

class LogAnalyzer:
    """Analyze logs from Elasticsearch"""

    def __init__(self, es_host: str = "localhost:9200",
                 username: str = "elastic",
                 password: str = "changeme"):
        self.es = Elasticsearch(
            [es_host],
            basic_auth=(username, password)
        )
        self.index_pattern = "mcp-mesh-logs-*"

    def search_by_trace_id(self, trace_id: str):
        """Find all logs for a specific trace"""
        query = {
            "query": {
                "term": {
                    "trace.trace_id": trace_id
                }
            },
            "sort": [
                {"timestamp": "asc"}
            ],
            "size": 1000
        }

        response = self.es.search(
            index=self.index_pattern,
            body=query
        )

        return [hit["_source"] for hit in response["hits"]["hits"]]

    def find_errors_by_agent(self, agent_name: str,
                            hours: int = 24):
        """Find recent errors for an agent"""
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"agent.name": agent_name}},
                        {"term": {"level": "ERROR"}},
                        {"range": {
                            "timestamp": {
                                "gte": f"now-{hours}h"
                            }
                        }}
                    ]
                }
            },
            "aggs": {
                "error_types": {
                    "terms": {
                        "field": "exception.type",
                        "size": 10
                    }
                },
                "error_timeline": {
                    "date_histogram": {
                        "field": "timestamp",
                        "fixed_interval": "1h"
                    }
                }
            },
            "size": 100
        }

        response = self.es.search(
            index=self.index_pattern,
            body=query
        )

        return {
            "errors": [hit["_source"] for hit in response["hits"]["hits"]],
            "error_types": response["aggregations"]["error_types"]["buckets"],
            "timeline": response["aggregations"]["error_timeline"]["buckets"]
        }

    def analyze_request_patterns(self, hours: int = 1):
        """Analyze request patterns across all agents"""
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": "request.method"}},
                        {"range": {
                            "timestamp": {
                                "gte": f"now-{hours}h"
                            }
                        }}
                    ]
                }
            },
            "aggs": {
                "requests_by_agent": {
                    "terms": {
                        "field": "agent.name",
                        "size": 20
                    },
                    "aggs": {
                        "methods": {
                            "terms": {
                                "field": "request.method",
                                "size": 10
                            }
                        },
                        "avg_duration": {
                            "avg": {
                                "field": "request.duration_ms"
                            }
                        },
                        "error_rate": {
                            "terms": {
                                "field": "request.status",
                                "size": 2
                            }
                        }
                    }
                },
                "slow_requests": {
                    "top_hits": {
                        "sort": [
                            {"request.duration_ms": "desc"}
                        ],
                        "size": 10,
                        "_source": ["timestamp", "agent.name",
                                   "request.method", "request.duration_ms"]
                    }
                }
            },
            "size": 0
        }

        response = self.es.search(
            index=self.index_pattern,
            body=query
        )

        return response["aggregations"]

    def detect_anomalies(self, agent_name: str):
        """Detect anomalous patterns in logs"""
        # Use machine learning features if available
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"agent.name": agent_name}},
                        {"range": {
                            "timestamp": {
                                "gte": "now-1h"
                            }
                        }}
                    ]
                }
            },
            "aggs": {
                "log_rate": {
                    "date_histogram": {
                        "field": "timestamp",
                        "fixed_interval": "1m"
                    },
                    "aggs": {
                        "level_breakdown": {
                            "terms": {
                                "field": "level"
                            }
                        }
                    }
                },
                "unique_errors": {
                    "cardinality": {
                        "field": "exception.message.keyword"
                    }
                },
                "rare_terms": {
                    "rare_terms": {
                        "field": "msg.keyword",
                        "max_doc_count": 2
                    }
                }
            }
        }

        response = self.es.search(
            index=self.index_pattern,
            body=query
        )

        # Analyze for anomalies
        anomalies = []

        # Check for sudden spike in errors
        for bucket in response["aggregations"]["log_rate"]["buckets"]:
            error_count = next(
                (b["doc_count"] for b in bucket["level_breakdown"]["buckets"]
                 if b["key"] == "ERROR"), 0
            )
            if error_count > 10:  # Threshold
                anomalies.append({
                    "type": "error_spike",
                    "timestamp": bucket["key_as_string"],
                    "count": error_count
                })

        # Check for new error types
        unique_errors = response["aggregations"]["unique_errors"]["value"]
        if unique_errors > 5:  # Threshold
            anomalies.append({
                "type": "high_error_variety",
                "unique_count": unique_errors
            })

        return anomalies

    def export_logs(self, query: dict, output_file: str):
        """Export logs matching query to file"""
        from elasticsearch.helpers import scan

        with open(output_file, 'w') as f:
            for doc in scan(
                self.es,
                index=self.index_pattern,
                query=query,
                size=1000
            ):
                f.write(json.dumps(doc["_source"]) + "\n")

# Usage example
analyzer = LogAnalyzer()

# Find logs for a trace
trace_logs = analyzer.search_by_trace_id("abc123def456")
for log in trace_logs:
    print(f"{log['timestamp']} [{log['level']}] {log['msg']}")

# Analyze errors
errors = analyzer.find_errors_by_agent("weather-agent")
print(f"Found {len(errors['errors'])} errors")
for error_type in errors['error_types']:
    print(f"  {error_type['key']}: {error_type['doc_count']}")

# Detect anomalies
anomalies = analyzer.detect_anomalies("payment-agent")
if anomalies:
    print("Anomalies detected:")
    for anomaly in anomalies:
        print(f"  {anomaly['type']}: {anomaly}")
```

### Step 6: Set Up Log Retention and Archival

Configure log lifecycle management:

```bash
# Create S3 repository for snapshots
curl -X PUT "localhost:9200/_snapshot/mcp_mesh_backup" \
  -H "Content-Type: application/json" \
  -u elastic:changeme \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "mcp-mesh-logs-backup",
      "region": "us-east-1",
      "access_key": "YOUR_ACCESS_KEY",
      "secret_key": "YOUR_SECRET_KEY"
    }
  }'

# Create snapshot lifecycle policy
curl -X PUT "localhost:9200/_slm/policy/daily-snapshots" \
  -H "Content-Type: application/json" \
  -u elastic:changeme \
  -d '{
    "schedule": "0 30 1 * * ?",
    "name": "<mcp-mesh-logs-{now/d}>",
    "repository": "mcp_mesh_backup",
    "config": {
      "indices": ["mcp-mesh-logs-*"],
      "include_global_state": false,
      "partial": false
    },
    "retention": {
      "expire_after": "90d",
      "min_count": 5,
      "max_count": 50
    }
  }'
```

## Configuration Options

| Component        | Setting   | Description                       |
| ---------------- | --------- | --------------------------------- |
| Index Shards     | `3`       | Number of primary shards          |
| Retention        | `30 days` | How long to keep logs             |
| Refresh Interval | `5s`      | How often to make logs searchable |
| Batch Size       | `2MB`     | Fluentd batch size                |
| Replicas         | `1`       | Number of replica shards          |

## Examples

### Example 1: Security Audit Dashboard

```json
{
  "dashboard": {
    "title": "MCP Mesh Security Audit",
    "panels": [
      {
        "title": "Authentication Events",
        "query": {
          "query_string": {
            "query": "audit.action:(login OR logout OR auth_failure)"
          }
        },
        "visualization": "data_table"
      },
      {
        "title": "Access Patterns by User",
        "query": {
          "bool": {
            "must": [
              { "exists": { "field": "audit.user_id" } },
              { "term": { "audit.result": "success" } }
            ]
          }
        },
        "visualization": "heatmap",
        "x_axis": "timestamp",
        "y_axis": "audit.user_id"
      },
      {
        "title": "Failed Access Attempts",
        "query": {
          "bool": {
            "must": [
              { "term": { "audit.result": "failure" } },
              { "range": { "timestamp": { "gte": "now-1h" } } }
            ]
          }
        },
        "visualization": "map",
        "geo_field": "client.geo.location"
      }
    ]
  }
}
```

### Example 2: Performance Analysis

```python
# performance_logs.py
def analyze_performance_logs(es_client, agent_name: str):
    """Analyze performance from logs"""

    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"agent.name": agent_name}},
                    {"exists": {"field": "metrics.duration_ms"}},
                    {"range": {"timestamp": {"gte": "now-1h"}}}
                ]
            }
        },
        "aggs": {
            "percentiles": {
                "percentiles": {
                    "field": "metrics.duration_ms",
                    "percents": [50, 95, 99]
                }
            },
            "outliers": {
                "terms": {
                    "field": "request.method",
                    "size": 10,
                    "order": {"max_duration": "desc"}
                },
                "aggs": {
                    "max_duration": {
                        "max": {"field": "metrics.duration_ms"}
                    },
                    "sample_logs": {
                        "top_hits": {
                            "size": 1,
                            "sort": [{"metrics.duration_ms": "desc"}]
                        }
                    }
                }
            }
        }
    }

    result = es_client.search(index="mcp-mesh-logs-*", body=query)

    print(f"Performance Analysis for {agent_name}:")
    print(f"P50: {result['aggregations']['percentiles']['values']['50.0']}ms")
    print(f"P95: {result['aggregations']['percentiles']['values']['95.0']}ms")
    print(f"P99: {result['aggregations']['percentiles']['values']['99.0']}ms")

    print("\nSlowest Operations:")
    for bucket in result['aggregations']['outliers']['buckets']:
        print(f"  {bucket['key']}: {bucket['max_duration']['value']}ms")
```

## Best Practices

1. **Structured Logging**: Always use JSON format
2. **Correlation IDs**: Include trace and request IDs
3. **Log Levels**: Use appropriate levels consistently
4. **Retention Policy**: Balance cost with compliance
5. **Security**: Never log sensitive data

## Common Pitfalls

### Pitfall 1: Logging Too Much

**Problem**: Excessive logging impacts performance and storage

**Solution**: Implement smart logging:

```python
# Use sampling for high-frequency logs
if random.random() < 0.01:  # 1% sampling
    logger.debug("High frequency event", sampled=True)

# Aggregate before logging
if time.time() - self.last_log > 60:  # Log every minute
    logger.info(f"Processed {self.count} requests", count=self.count)
    self.count = 0
    self.last_log = time.time()
```

### Pitfall 2: Missing Context

**Problem**: Logs lack context for troubleshooting

**Solution**: Always include relevant context:

```python
logger.error(
    "Database connection failed",
    error=str(e),
    database_host=db_config["host"],
    retry_count=retry_count,
    connection_pool_size=pool.size,
    active_connections=pool.active_count
)
```

## Testing

### Test Log Pipeline

```python
# test_logging.py
import pytest
import json
from io import StringIO
import logging

def test_structured_logging():
    """Test that logs are properly structured"""
    stream = StringIO()
    handler = logging.StreamHandler(stream)

    logger = setup_logging("test-service")
    logger.handlers = [handler]

    # Log test message
    with LogContext(request_id="test-123"):
        logger.info("Test message", custom_field="value")

    # Parse log output
    stream.seek(0)
    log_data = json.loads(stream.getvalue())

    # Verify structure
    assert log_data["level"] == "INFO"
    assert log_data["msg"] == "Test message"
    assert log_data["custom_field"] == "value"
    assert log_data["request_id"] == "test-123"
    assert "timestamp" in log_data
    assert "service" in log_data

def test_exception_logging():
    """Test exception logging"""
    logger = AgentLogger("test-agent")

    try:
        raise ValueError("Test error")
    except ValueError as e:
        logger.exception("Operation failed", e, operation="test_op")

    # Verify exception was logged with context
    # (Would need to capture and verify in real test)
```

### Load Test Logging

```bash
#!/bin/bash
# load-test-logging.sh

echo "Testing logging pipeline under load..."

# Generate high log volume
for i in {1..10000}; do
  echo '{"timestamp":"2024-01-15T10:00:00Z","level":"INFO","msg":"Test log '$i'","service":{"name":"load-test"}}' | \
    curl -X POST "http://localhost:9200/mcp-mesh-logs/_doc" \
      -H "Content-Type: application/json" \
      -u elastic:changeme \
      --data-binary @- &

  if [ $((i % 100)) -eq 0 ]; then
    wait
  fi
done

# Check ingestion rate
curl -s "http://localhost:9200/mcp-mesh-logs/_stats/indexing" \
  -u elastic:changeme | \
  jq '.indices["mcp-mesh-logs"].primaries.indexing.index_total'
```

## Monitoring and Debugging

### Monitor Log Pipeline Health

```yaml
# logging-monitoring.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: logging-alerts
  namespace: logging
data:
  alerts.yaml: |
    groups:
    - name: logging
      rules:
      - alert: LogIngestionRate
        expr: |
          rate(fluentd_output_status_num_records_total[5m]) < 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low log ingestion rate"
          description: "Log ingestion rate is {{ $value }} logs/sec"

      - alert: ElasticsearchDiskSpace
        expr: |
          elasticsearch_filesystem_data_available_bytes /
          elasticsearch_filesystem_data_size_bytes < 0.1
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Elasticsearch disk space low"

      - alert: LogParsingErrors
        expr: |
          rate(fluentd_filter_records_total{result="error"}[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High log parsing error rate"
```

### Debug Log Issues

```bash
# Check Fluentd status
kubectl logs -n logging daemonset/fluentd

# Test log parsing
echo '{"timestamp":"2024-01-15T10:00:00Z","level":"INFO","msg":"Test"}' | \
  kubectl exec -n logging fluentd-xxxxx -- \
  fluentd -c /fluentd/etc/fluent.conf --dry-run

# Check Elasticsearch health
curl -s http://localhost:9200/_cluster/health?pretty -u elastic:changeme

# View index stats
curl -s http://localhost:9200/mcp-mesh-logs-*/_stats?pretty -u elastic:changeme
```

## 🔧 Troubleshooting

### Issue 1: Logs Not Appearing

**Symptoms**: Logs not visible in Kibana

**Cause**: Parsing errors or connection issues

**Solution**:

```bash
# Check Fluentd logs for errors
kubectl logs -n logging daemonset/fluentd | grep ERROR

# Verify index exists
curl -s http://localhost:9200/_cat/indices/mcp-mesh-logs-* -u elastic:changeme

# Check for parsing errors
kubectl exec -n logging fluentd-xxxxx -- \
  cat /var/log/fluentd-containers.log.pos
```

### Issue 2: High Memory Usage

**Symptoms**: Elasticsearch using too much memory

**Cause**: Large indices or inefficient queries

**Solution**:

```bash
# Force merge old indices
curl -X POST "http://localhost:9200/mcp-mesh-logs-*/_forcemerge?max_num_segments=1" \
  -u elastic:changeme

# Update index settings
curl -X PUT "http://localhost:9200/mcp-mesh-logs-*/_settings" \
  -H "Content-Type: application/json" \
  -u elastic:changeme \
  -d '{
    "index": {
      "refresh_interval": "30s",
      "number_of_replicas": 0
    }
  }'
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Index Size**: Single index limited by shard size
- **Query Performance**: Complex queries can be slow
- **Storage Cost**: Logs consume significant disk space
- **Retention Trade-offs**: Longer retention increases costs

## 📝 TODO

- [ ] Add log anomaly detection with ML
- [ ] Implement log sampling strategies
- [ ] Create automated log analysis reports
- [ ] Add integration with SIEM tools
- [ ] Document multi-region log aggregation

## Summary

You now have centralized logging implemented:

Key takeaways:

- 🔑 All logs aggregated in Elasticsearch
- 🔑 Structured logging with full context
- 🔑 Powerful search and analysis capabilities
- 🔑 Correlation with traces and metrics

## Next Steps

Let's complete observability with alerting and SLOs.

Continue to [Alerting and SLOs](./05-alerting-slos.md) →

---

💡 **Tip**: Use Kibana's machine learning features to detect anomalies in log patterns automatically

📚 **Reference**: [Elastic Stack Documentation](https://www.elastic.co/guide/index.html)

🧪 **Try It**: Create a custom log dashboard for your specific use case using Kibana Lens

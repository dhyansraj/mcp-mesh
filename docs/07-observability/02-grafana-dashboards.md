---
render_with_liquid: false
---

# Grafana Dashboards

> Visualize and analyze MCP Mesh metrics with powerful, customizable dashboards

## Overview

Grafana provides rich visualization capabilities for monitoring MCP Mesh deployments. This guide covers creating comprehensive dashboards, implementing drill-down navigation, setting up variables for dynamic filtering, and sharing dashboards across teams. You'll learn to build dashboards that provide actionable insights into agent performance, system health, and business metrics.

Well-designed Grafana dashboards transform raw metrics into meaningful visualizations that enable quick decision-making and proactive issue resolution.

## Key Concepts

- **Dashboard Organization**: Logical grouping and navigation
- **Panel Types**: Time series, stat, gauge, heatmap, logs
- **Variables**: Dynamic filtering and drill-down
- **Annotations**: Correlating events with metrics
- **Alerting**: Visual alerts and notifications

## Step-by-Step Guide

### Step 1: Access and Configure Grafana

Connect to Grafana and configure data sources:

```bash
# Port forward to Grafana
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80

# Default credentials (from kube-prometheus-stack)
# Username: admin
# Password: prom-operator

# Or get password from secret
kubectl get secret -n monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode
```

Configure Prometheus data source:

```yaml
# datasource-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasources
  namespace: monitoring
data:
  prometheus.yaml: |
    apiVersion: 1
    datasources:
    - name: Prometheus
      type: prometheus
      access: proxy
      url: http://prometheus-operated:9090
      isDefault: true
      jsonData:
        timeInterval: 30s
        queryTimeout: 60s
        httpMethod: POST
      # Enable exemplars for trace correlation
      exemplarTraceIdDestinations:
      - name: traceID
        datasourceUid: tempo
```

### Step 2: Create MCP Mesh Overview Dashboard

Create a comprehensive overview dashboard:

```json
{
  "dashboard": {
    "title": "MCP Mesh Overview",
    "uid": "mcp-mesh-overview",
    "description": "High-level overview of MCP Mesh platform health and performance",
    "tags": ["mcp-mesh", "overview"],
    "timezone": "browser",
    "schemaVersion": 30,
    "version": 1,
    "refresh": "30s",

    "variables": {
      "list": [
        {
          "name": "namespace",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(mcp_mesh_requests_total, namespace)",
          "refresh": 1,
          "multi": false,
          "includeAll": true,
          "allValue": ".*"
        },
        {
          "name": "agent",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(mcp_mesh_requests_total{namespace=~\"$namespace\"}, agent)",
          "refresh": 1,
          "multi": true,
          "includeAll": true,
          "allValue": ".*"
        },
        {
          "name": "interval",
          "type": "interval",
          "options": [
            { "text": "1m", "value": "1m" },
            { "text": "5m", "value": "5m" },
            { "text": "10m", "value": "10m" },
            { "text": "30m", "value": "30m" },
            { "text": "1h", "value": "1h" }
          ],
          "current": {
            "text": "5m",
            "value": "5m"
          }
        }
      ]
    },

    "panels": [
      {
        "title": "System Health Score",
        "type": "stat",
        "gridPos": { "h": 4, "w": 6, "x": 0, "y": 0 },
        "targets": [
          {
            "expr": "avg(mcp_mesh:registry:health_score)",
            "refId": "A"
          }
        ],
        "options": {
          "reduceOptions": {
            "calcs": ["lastNotNull"]
          },
          "colorMode": "background",
          "graphMode": "none",
          "orientation": "horizontal"
        },
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "red", "value": 0 },
                { "color": "yellow", "value": 80 },
                { "color": "green", "value": 95 }
              ]
            }
          }
        }
      },

      {
        "title": "Active Agents",
        "type": "stat",
        "gridPos": { "h": 4, "w": 6, "x": 6, "y": 0 },
        "targets": [
          {
            "expr": "count(up{job=~\"mcp-mesh.*\", namespace=~\"$namespace\"} == 1)",
            "refId": "A"
          }
        ],
        "options": {
          "colorMode": "value",
          "graphMode": "area",
          "orientation": "horizontal"
        }
      },

      {
        "title": "Total Request Rate",
        "type": "stat",
        "gridPos": { "h": 4, "w": 6, "x": 12, "y": 0 },
        "targets": [
          {
            "expr": "sum(rate(mcp_mesh_requests_total{namespace=~\"$namespace\", agent=~\"$agent\"}[$interval]))",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "reqps",
            "decimals": 2
          }
        }
      },

      {
        "title": "Error Rate",
        "type": "stat",
        "gridPos": { "h": 4, "w": 6, "x": 18, "y": 0 },
        "targets": [
          {
            "expr": "sum(rate(mcp_mesh_requests_total{namespace=~\"$namespace\", agent=~\"$agent\", status=\"error\"}[$interval])) / sum(rate(mcp_mesh_requests_total{namespace=~\"$namespace\", agent=~\"$agent\"}[$interval])) * 100",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "decimals": 2,
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "green", "value": 0 },
                { "color": "yellow", "value": 1 },
                { "color": "red", "value": 5 }
              ]
            }
          }
        }
      },

      {
        "title": "Request Rate by Agent",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 4 },
        "targets": [
          {
            "expr": "sum by (agent) (rate(mcp_mesh_requests_total{namespace=~\"$namespace\", agent=~\"$agent\"}[$interval]))",
            "legendFormat": "{% raw %}{{agent}}{% endraw %}",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "reqps",
            "custom": {
              "drawStyle": "line",
              "lineInterpolation": "smooth",
              "lineWidth": 2,
              "fillOpacity": 10,
              "gradientMode": "opacity",
              "spanNulls": false,
              "showPoints": "never",
              "stacking": {
                "mode": "none"
              }
            }
          }
        }
      },

      {
        "title": "Response Time Heatmap",
        "type": "heatmap",
        "gridPos": { "h": 8, "w": 12, "x": 12, "y": 4 },
        "targets": [
          {
            "expr": "sum by (le) (increase(mcp_mesh_request_duration_seconds_bucket{namespace=~\"$namespace\", agent=~\"$agent\"}[$interval]))",
            "format": "heatmap",
            "refId": "A"
          }
        ],
        "options": {
          "calculate": false,
          "yAxis": {
            "unit": "s",
            "decimals": 2
          },
          "cellGap": 1,
          "colorScheme": "interpolateSpectral"
        }
      }
    ]
  }
}
```

### Step 3: Create Agent-Specific Dashboard

Build detailed dashboards for individual agents:

```json
{
  "dashboard": {
    "title": "MCP Mesh Agent Details",
    "uid": "mcp-mesh-agent-details",
    "description": "Detailed metrics for individual MCP Mesh agents",

    "panels": [
      {
        "title": "Agent Info",
        "type": "table",
        "gridPos": { "h": 4, "w": 24, "x": 0, "y": 0 },
        "targets": [
          {
            "expr": "mcp_mesh_agent{agent=\"$agent\"}",
            "format": "table",
            "instant": true,
            "refId": "A"
          }
        ],
        "transformations": [
          {
            "id": "filterFieldsByName",
            "options": {
              "include": {
                "names": ["agent_name", "version", "capabilities", "Value"]
              }
            }
          }
        ]
      },

      {
        "title": "Request Latency Percentiles",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 4 },
        "targets": [
          {
            "expr": "histogram_quantile(0.50, sum by (le) (rate(mcp_mesh_request_duration_seconds_bucket{agent=\"$agent\"}[$interval])))",
            "legendFormat": "p50",
            "refId": "A"
          },
          {
            "expr": "histogram_quantile(0.95, sum by (le) (rate(mcp_mesh_request_duration_seconds_bucket{agent=\"$agent\"}[$interval])))",
            "legendFormat": "p95",
            "refId": "B"
          },
          {
            "expr": "histogram_quantile(0.99, sum by (le) (rate(mcp_mesh_request_duration_seconds_bucket{agent=\"$agent\"}[$interval])))",
            "legendFormat": "p99",
            "refId": "C"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "s",
            "custom": {
              "axisLabel": "Response Time",
              "drawStyle": "line",
              "lineWidth": 2,
              "fillOpacity": 0
            }
          },
          "overrides": [
            {
              "matcher": { "id": "byName", "options": "p99" },
              "properties": [
                {
                  "id": "color",
                  "value": { "mode": "fixed", "fixedColor": "red" }
                }
              ]
            }
          ]
        }
      },

      {
        "title": "Request Types Distribution",
        "type": "piechart",
        "gridPos": { "h": 8, "w": 12, "x": 12, "y": 4 },
        "targets": [
          {
            "expr": "sum by (method) (increase(mcp_mesh_requests_total{agent=\"$agent\"}[$interval]))",
            "legendFormat": "{% raw %}{{method}}{% endraw %}",
            "refId": "A"
          }
        ],
        "options": {
          "reduceOptions": {
            "values": false,
            "calcs": ["lastNotNull"]
          },
          "pieType": "donut",
          "displayLabels": ["name", "percent"],
          "legendDisplayMode": "table",
          "legendPlacement": "right"
        }
      },

      {
        "title": "Active Connections",
        "type": "graph",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 12 },
        "targets": [
          {
            "expr": "mcp_mesh_connections_active{agent=\"$agent\"}",
            "legendFormat": "{% raw %}{{type}}{% endraw %}",
            "refId": "A"
          }
        ],
        "yaxes": [
          {
            "label": "Connections",
            "format": "short",
            "min": 0
          }
        ]
      },

      {
        "title": "Resource Usage",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 12, "y": 12 },
        "targets": [
          {
            "expr": "rate(container_cpu_usage_seconds_total{pod=~\"$agent.*\"}[$interval]) * 100",
            "legendFormat": "CPU %",
            "refId": "A"
          },
          {
            "expr": "container_memory_working_set_bytes{pod=~\"$agent.*\"} / 1024 / 1024",
            "legendFormat": "Memory (MB)",
            "refId": "B"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "custom": {
              "drawStyle": "line",
              "lineWidth": 2,
              "fillOpacity": 10
            }
          },
          "overrides": [
            {
              "matcher": { "id": "byName", "options": "CPU %" },
              "properties": [
                { "id": "unit", "value": "percent" },
                { "id": "custom.axisPlacement", "value": "left" }
              ]
            },
            {
              "matcher": { "id": "byName", "options": "Memory (MB)" },
              "properties": [
                { "id": "unit", "value": "decmbytes" },
                { "id": "custom.axisPlacement", "value": "right" }
              ]
            }
          ]
        }
      }
    ]
  }
}
```

### Step 4: Create Business Metrics Dashboard

Visualize business-specific KPIs:

```json
{
  "dashboard": {
    "title": "MCP Mesh Business Metrics",
    "uid": "mcp-mesh-business",
    "description": "Business KPIs and analytics for MCP Mesh",

    "panels": [
      {
        "title": "Revenue by Agent",
        "type": "bargauge",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
        "targets": [
          {
            "expr": "sum by (agent) (increase(mcp_mesh_business_revenue_total[$__range]))",
            "legendFormat": "{% raw %}{{agent}}{% endraw %}",
            "refId": "A"
          }
        ],
        "options": {
          "orientation": "horizontal",
          "displayMode": "gradient",
          "showUnfilled": true
        },
        "fieldConfig": {
          "defaults": {
            "unit": "currencyUSD",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "green", "value": 0 },
                { "color": "yellow", "value": 10000 },
                { "color": "red", "value": 50000 }
              ]
            }
          }
        }
      },

      {
        "title": "API Usage Costs",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
        "targets": [
          {
            "expr": "sum by (api_provider) (increase(mcp_mesh_business_api_calls_total[$interval]) * 0.001)",
            "legendFormat": "{% raw %}{{api_provider}}{% endraw %} ($0.001/call)",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "currencyUSD",
            "custom": {
              "stacking": {
                "mode": "normal"
              },
              "fillOpacity": 50
            }
          }
        }
      },

      {
        "title": "Cache Performance",
        "type": "gauge",
        "gridPos": { "h": 8, "w": 8, "x": 0, "y": 8 },
        "targets": [
          {
            "expr": "avg(mcp_mesh_cache_hit_rate)",
            "refId": "A"
          }
        ],
        "options": {
          "orientation": "auto",
          "showThresholdLabels": true,
          "showThresholdMarkers": true
        },
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "min": 0,
            "max": 100,
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "red", "value": 0 },
                { "color": "yellow", "value": 60 },
                { "color": "green", "value": 80 }
              ]
            }
          }
        }
      },

      {
        "title": "SLO Compliance",
        "type": "stat",
        "gridPos": { "h": 8, "w": 8, "x": 8, "y": 8 },
        "targets": [
          {
            "expr": "avg(mcp_mesh:slo:availability) * 100",
            "refId": "A"
          }
        ],
        "options": {
          "colorMode": "background",
          "graphMode": "none",
          "orientation": "horizontal"
        },
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "decimals": 3,
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "red", "value": 0 },
                { "color": "yellow", "value": 99 },
                { "color": "green", "value": 99.9 }
              ]
            }
          }
        }
      },

      {
        "title": "Cost per Transaction",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 8, "x": 16, "y": 8 },
        "targets": [
          {
            "expr": "(sum(rate(container_cpu_usage_seconds_total{namespace=\"mcp-mesh\"}[$interval])) * 0.05 + sum(container_memory_working_set_bytes{namespace=\"mcp-mesh\"}) / 1024 / 1024 / 1024 * 0.01) / sum(rate(mcp_mesh_requests_total[$interval]))",
            "legendFormat": "Cost per transaction",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "currencyUSD",
            "decimals": 6,
            "custom": {
              "drawStyle": "line",
              "lineWidth": 2,
              "fillOpacity": 20,
              "gradientMode": "opacity"
            }
          }
        }
      }
    ]
  }
}
```

### Step 5: Implement Dynamic Dashboards

Create dashboards with advanced features:

```yaml
# dashboard-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboards-dynamic
  namespace: monitoring
data:
  dynamic-dashboard.json: |
    {
      "dashboard": {
        "title": "MCP Mesh Dynamic Analysis",
        "templating": {
          "list": [
            {
              "name": "datasource",
              "type": "datasource",
              "query": "prometheus",
              "current": {
                "text": "Prometheus",
                "value": "Prometheus"
              }
            },
            {
              "name": "agent_regex",
              "type": "textbox",
              "current": {
                "text": ".*",
                "value": ".*"
              },
              "label": "Agent Filter (regex)"
            },
            {
              "name": "percentile",
              "type": "custom",
              "current": {
                "text": "0.95",
                "value": "0.95"
              },
              "options": [
                {"text": "p50", "value": "0.5"},
                {"text": "p90", "value": "0.9"},
                {"text": "p95", "value": "0.95"},
                {"text": "p99", "value": "0.99"}
              ]
            }
          ]
        },

        "annotations": {
          "list": [
            {
              "datasource": "Prometheus",
              "enable": true,
              "expr": "changes(mcp_mesh_agent{agent=~\"$agent_regex\"}[5m]) > 0",
              "iconColor": "rgba(0, 211, 255, 1)",
              "name": "Agent Restarts",
              "tagKeys": "agent,version"
            },
            {
              "datasource": "Prometheus",
              "enable": true,
              "expr": "ALERTS{alertstate=\"firing\",namespace=\"mcp-mesh\"}",
              "iconColor": "rgba(255, 96, 96, 1)",
              "name": "Active Alerts",
              "tagKeys": "alertname,severity"
            }
          ]
        },

        "links": [
          {
            "title": "Drill Down",
            "type": "dashboards",
            "tags": ["mcp-mesh", "agent"],
            "includeVars": true,
            "keepTime": true
          },
          {
            "title": "View in Jaeger",
            "type": "link",
            "url": "http://jaeger:16686/search?service=${agent}&start=${__from}&end=${__to}",
            "targetBlank": true
          }
        ],

        "panels": [
          {
            "title": "Dynamic Latency Analysis",
            "type": "graph",
            "gridPos": {"h": 10, "w": 24, "x": 0, "y": 0},
            "targets": [
              {
                "expr": "histogram_quantile($percentile, sum by (agent, le) (rate(mcp_mesh_request_duration_seconds_bucket{agent=~\"$agent_regex\"}[$interval])))",
                "legendFormat": "{% raw %}{{agent}}{% endraw %} - p${percentile:raw}",
                "refId": "A"
              }
            ],
            "options": {
              "dataLinks": [
                {
                  "title": "View traces",
                  "url": "/explore?left={\"datasource\":\"Tempo\",\"queries\":[{\"query\":\"agent=${__series.labels.agent}\"}],\"range\":{\"from\":\"${__value.time}\",\"to\":\"${__value.time}\"}}"
                }
              ]
            }
          },

          {
            "title": "Adaptive Thresholds",
            "type": "timeseries",
            "gridPos": {"h": 10, "w": 24, "x": 0, "y": 10},
            "targets": [
              {
                "expr": "mcp_mesh:request_rate{agent=~\"$agent_regex\"}",
                "legendFormat": "{% raw %}{{agent}}{% endraw %} - actual",
                "refId": "A"
              },
              {
                "expr": "predict_linear(mcp_mesh:request_rate{agent=~\"$agent_regex\"}[1h], 3600)",
                "legendFormat": "{% raw %}{{agent}}{% endraw %} - predicted",
                "refId": "B"
              },
              {
                "expr": "mcp_mesh:request_rate{agent=~\"$agent_regex\"} + 2 * stddev_over_time(mcp_mesh:request_rate{agent=~\"$agent_regex\"}[1h])",
                "legendFormat": "{% raw %}{{agent}}{% endraw %} - upper bound",
                "refId": "C"
              }
            ],
            "fieldConfig": {
              "overrides": [
                {
                  "matcher": {"id": "byRegexp", "options": ".*predicted.*"},
                  "properties": [
                    {
                      "id": "custom.lineStyle",
                      "value": {"fill": "dash", "dash": [10, 10]}
                    }
                  ]
                },
                {
                  "matcher": {"id": "byRegexp", "options": ".*upper bound.*"},
                  "properties": [
                    {
                      "id": "custom.lineStyle",
                      "value": {"fill": "dot", "dash": [2, 5]}
                    },
                    {
                      "id": "color",
                      "value": {"mode": "fixed", "fixedColor": "red"}
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

### Step 6: Set Up Dashboard Provisioning

Automate dashboard deployment:

```yaml
# dashboard-provisioning.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-provider
  namespace: monitoring
data:
  dashboards.yaml: |
    apiVersion: 1
    providers:
    - name: 'MCP Mesh Dashboards'
      orgId: 1
      folder: 'MCP Mesh'
      type: file
      disableDeletion: false
      updateIntervalSeconds: 10
      allowUiUpdates: true
      options:
        path: /var/lib/grafana/dashboards/mcp-mesh

    - name: 'MCP Mesh Generated'
      orgId: 1
      folder: 'MCP Mesh - Auto'
      type: file
      disableDeletion: true
      updateIntervalSeconds: 30
      options:
        path: /var/lib/grafana/dashboards/generated

---
# Script to generate dashboards dynamically
apiVersion: v1
kind: ConfigMap
metadata:
  name: dashboard-generator
  namespace: monitoring
data:
  generate.py: |
    #!/usr/bin/env python3
    import json
    import os
    from prometheus_api_client import PrometheusConnect

    # Connect to Prometheus
    prom = PrometheusConnect(url="http://prometheus-operated:9090")

    # Get all agents
    agents = prom.custom_query('group by (agent) (mcp_mesh_requests_total)')

    # Generate dashboard for each agent
    for agent_data in agents:
        agent = agent_data['metric']['agent']

        dashboard = {
            "dashboard": {
                "title": f"MCP Mesh - {agent}",
                "uid": f"mcp-mesh-auto-{agent}",
                "tags": ["mcp-mesh", "auto-generated", agent],
                "panels": generate_panels_for_agent(agent)
            }
        }

        # Save dashboard
        with open(f'/var/lib/grafana/dashboards/generated/{agent}.json', 'w') as f:
            json.dump(dashboard, f, indent=2)

    def generate_panels_for_agent(agent):
        return [
            {
                "title": f"{agent} - Request Rate",
                "type": "graph",
                "targets": [
                    {
                        "expr": f'rate(mcp_mesh_requests_total{% raw %}{{agent="{agent}"}}{% endraw %}[5m])',
                        "refId": "A"
                    }
                ]
            }
            # Add more panels...
        ]
```

## Configuration Options

| Feature     | Configuration      | Purpose                       |
| ----------- | ------------------ | ----------------------------- |
| Variables   | `templating.list`  | Dynamic filtering             |
| Annotations | `annotations.list` | Event markers                 |
| Links       | `links`            | Navigation between dashboards |
| Alerts      | `alert`            | Visual alert rules            |
| Transforms  | `transformations`  | Data manipulation             |

## Examples

### Example 1: Multi-Cluster Dashboard

```json
{
  "dashboard": {
    "title": "MCP Mesh Multi-Cluster View",
    "panels": [
      {
        "title": "Cluster Comparison",
        "type": "table",
        "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
        "targets": [
          {
            "expr": "sum by (cluster, agent) (rate(mcp_mesh_requests_total[5m]))",
            "format": "table",
            "instant": true,
            "refId": "A"
          }
        ],
        "transformations": [
          {
            "id": "pivot",
            "options": {
              "pivotField": "cluster",
              "valueField": "Value",
              "groupByField": "agent"
            }
          }
        ],
        "fieldConfig": {
          "defaults": {
            "custom": {
              "displayMode": "color-background",
              "colorMode": "value"
            },
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "green", "value": 0 },
                { "color": "yellow", "value": 10 },
                { "color": "red", "value": 50 }
              ]
            }
          }
        }
      }
    ]
  }
}
```

### Example 2: SLO Dashboard

```json
{
  "dashboard": {
    "title": "MCP Mesh SLO Tracking",
    "panels": [
      {
        "title": "Error Budget Remaining",
        "type": "gauge",
        "targets": [
          {
            "expr": "(1 - ((1 - avg(mcp_mesh:slo:availability)) / (1 - 0.999))) * 100",
            "refId": "A"
          }
        ],
        "options": {
          "showThresholdLabels": true,
          "showThresholdMarkers": true,
          "text": {
            "titleSize": 24,
            "valueSize": 48
          }
        },
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "min": 0,
            "max": 100,
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "red", "value": 0 },
                { "color": "yellow", "value": 25 },
                { "color": "green", "value": 50 }
              ]
            }
          }
        }
      },

      {
        "title": "SLO Burn Rate",
        "type": "timeseries",
        "targets": [
          {
            "expr": "1 - mcp_mesh:slo:availability",
            "legendFormat": "Current burn rate",
            "refId": "A"
          },
          {
            "expr": "0.001",
            "legendFormat": "SLO threshold (99.9%)",
            "refId": "B"
          }
        ]
      }
    ]
  }
}
```

## Best Practices

1. **Organize Dashboards**: Use folders and tags
2. **Use Variables**: Enable dynamic filtering
3. **Add Documentation**: Include panel descriptions
4. **Set Refresh Rates**: Balance freshness vs load
5. **Export/Import**: Version control dashboards

## Common Pitfalls

### Pitfall 1: Overwhelming Dashboards

**Problem**: Too many panels, hard to understand

**Solution**: Create focused dashboards:

```json
{
  "dashboard": {
    "title": "MCP Mesh - Quick Health",
    "description": "High-level health indicators only",
    "panels": [
      // Limit to 6-8 key metrics
    ]
  }
}
```

### Pitfall 2: Slow Queries

**Problem**: Dashboard takes forever to load

**Solution**: Use recording rules:

```promql
# Instead of complex query in dashboard
histogram_quantile(0.95,
  sum by (le) (
    rate(mcp_mesh_request_duration_seconds_bucket[5m])
  )
)

# Use pre-computed recording rule
mcp_mesh:request_duration:p95
```

## Testing

### Validate Dashboard JSON

```python
# test_dashboards.py
import json
import glob

def test_dashboard_validity():
    """Validate all dashboard JSON files"""
    for dashboard_file in glob.glob("dashboards/*.json"):
        with open(dashboard_file) as f:
            dashboard = json.load(f)

        # Check required fields
        assert "dashboard" in dashboard
        assert "title" in dashboard["dashboard"]
        assert "panels" in dashboard["dashboard"]

        # Check panels
        for panel in dashboard["dashboard"]["panels"]:
            assert "type" in panel
            assert "gridPos" in panel
            assert "targets" in panel

def test_dashboard_queries():
    """Validate Prometheus queries in dashboards"""
    from prometheus_api_client import PrometheusConnect

    prom = PrometheusConnect(url="http://localhost:9090")

    for dashboard_file in glob.glob("dashboards/*.json"):
        with open(dashboard_file) as f:
            dashboard = json.load(f)

        for panel in dashboard["dashboard"]["panels"]:
            for target in panel.get("targets", []):
                if "expr" in target:
                    # Test query syntax
                    try:
                        prom.custom_query(target["expr"])
                    except Exception as e:
                        raise AssertionError(
                            f"Invalid query in {dashboard_file}: {target['expr']}"
                        ) from e
```

### Performance Testing

```bash
#!/bin/bash
# test-dashboard-performance.sh

GRAFANA_URL="http://localhost:3000"
DASHBOARD_UID="mcp-mesh-overview"

# Measure dashboard load time
time curl -s -o /dev/null \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  "$GRAFANA_URL/api/dashboards/uid/$DASHBOARD_UID"

# Check panel query performance
curl -s \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  "$GRAFANA_URL/api/dashboards/uid/$DASHBOARD_UID" | \
  jq -r '.dashboard.panels[].targets[].expr' | \
  while read -r query; do
    echo "Testing query: $query"
    time curl -s -o /dev/null --data-urlencode "query=$query" \
      "http://prometheus:9090/api/v1/query"
  done
```

## Monitoring and Debugging

### Monitor Grafana Performance

```yaml
# grafana-monitoring.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-monitoring-dashboard
  namespace: monitoring
data:
  grafana-performance.json: |
    {
      "dashboard": {
        "title": "Grafana Performance",
        "panels": [
          {
            "title": "Dashboard Load Time",
            "type": "graph",
            "targets": [
              {
                "expr": "histogram_quantile(0.95, grafana_api_dashboard_get_milliseconds_bucket)",
                "legendFormat": "p95 load time"
              }
            ]
          },
          {
            "title": "Active Users",
            "type": "stat",
            "targets": [
              {
                "expr": "grafana_stat_active_users"
              }
            ]
          }
        ]
      }
    }
```

### Debug Dashboard Issues

```bash
# Enable debug logging
kubectl set env deployment/prometheus-grafana -n monitoring \
  GF_LOG_LEVEL=debug

# View Grafana logs
kubectl logs -n monitoring deployment/prometheus-grafana -f

# Check dashboard provisioning
kubectl exec -n monitoring deployment/prometheus-grafana -- \
  ls -la /var/lib/grafana/dashboards/

# Test data source connection
kubectl exec -n monitoring deployment/prometheus-grafana -- \
  curl -s http://prometheus-operated:9090/api/v1/query?query=up
```

## 🔧 Troubleshooting

### Issue 1: Dashboard Not Loading

**Symptoms**: Dashboard shows "No Data" or loading spinner

**Cause**: Data source misconfiguration or query errors

**Solution**:

```bash
# Check data source configuration
curl -s -H "Authorization: Bearer $API_KEY" \
  http://localhost:3000/api/datasources

# Test query directly in Prometheus
curl -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=mcp_mesh_requests_total'

# Check time range
# Ensure data exists for selected time range
```

### Issue 2: Variables Not Working

**Symptoms**: Template variables show "None" or don't filter

**Cause**: Incorrect query or label values

**Solution**:

```json
{
  "templating": {
    "list": [
      {
        "name": "agent",
        "type": "query",
        "datasource": "Prometheus",
        "query": "label_values(up{job=~\"mcp-mesh.*\"}, instance)",
        "refresh": 2, // on time range change
        "sort": 1 // alphabetical
      }
    ]
  }
}
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Panel Limit**: Performance degrades with >50 panels
- **Query Timeout**: Default 30s timeout for queries
- **Variable Cardinality**: High cardinality slows dropdown
- **Annotation Limit**: Too many annotations impact performance

## 📝 TODO

- [ ] Add dashboard templating with Jsonnet
- [ ] Create mobile-responsive dashboards
- [ ] Implement dashboard versioning
- [ ] Add automated screenshot testing
- [ ] Create dashboard marketplace

## Summary

You now have comprehensive Grafana dashboards for MCP Mesh:

Key takeaways:

- 🔑 Multi-level dashboards from overview to details
- 🔑 Dynamic filtering with variables
- 🔑 Performance optimization techniques
- 🔑 Automated provisioning and generation

## Next Steps

Let's add distributed tracing to correlate with metrics.

Continue to [Distributed Tracing](./03-distributed-tracing.md) →

---

💡 **Tip**: Use Grafana's built-in explore mode to test queries before adding to dashboards

📚 **Reference**: [Grafana Best Practices](https://grafana.com/docs/grafana/latest/best-practices/)

🧪 **Try It**: Create a custom dashboard for your specific use case using the examples as templates

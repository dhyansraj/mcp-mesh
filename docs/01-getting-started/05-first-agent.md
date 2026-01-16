# Creating Your First Agent

> Build a complete weather service agent using the dual decorator pattern

## Overview

In this guide, you'll create a sophisticated weather service agent that demonstrates:

- 🌤️ **Multiple MCP decorators** - `@app.tool`, `@app.prompt`, `@app.resource`
- 🔗 **Smart dependency injection** - Type-safe dependencies with tag-based resolution
- 📊 **Advanced patterns** - Self-dependencies and complex service integration
- 🎯 **Zero boilerplate** - No main methods or manual server setup
- 🏷️ **Tag-based resolution** - Intelligent service selection

## Project Structure

Create a new directory for your agent:

```bash
mkdir weather-agent
cd weather-agent

# Create the structure
touch weather_agent.py
touch requirements.txt
touch README.md
```

## Step 1: Basic Weather Agent with Dual Decorators

Create `weather_agent.py`:

```python
#!/usr/bin/env python3
"""
Advanced Weather Service Agent

Demonstrates:
- Dual decorator pattern (@app + @mesh)
- All MCP decorators (tool, prompt, resource)
- Smart dependency injection with type safety
- Tag-based service resolution
- Self-dependencies
"""

import json
import random
from datetime import datetime
from typing import Any

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Weather Service")

# Simulated weather data
WEATHER_CONDITIONS = ["sunny", "cloudy", "rainy", "snowy", "foggy", "windy"]
CITIES_DATA = {
    "new york": {"lat": 40.7128, "lon": -74.0060, "timezone": "EST"},
    "london": {"lat": 51.5074, "lon": -0.1278, "timezone": "GMT"},
    "tokyo": {"lat": 35.6762, "lon": 139.6503, "timezone": "JST"},
    "sydney": {"lat": -33.8688, "lon": 151.2093, "timezone": "AEST"},
    "paris": {"lat": 48.8566, "lon": 2.3522, "timezone": "CET"},
}

# ===== TOOLS with Smart Dependencies =====

@app.tool()
@mesh.tool(
    capability="time_service",
    tags=["weather", "time"],
    description="Get current time for weather timestamp"
)
def get_weather_time() -> str:
    """Get current time in weather service format."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

@app.tool()
@mesh.tool(
    capability="weather_data",
    dependencies=["time_service"],  # Self-dependency!
    tags=["weather", "core"],
    description="Get weather data for a city"
)
def get_weather(
    city: str,
    time_service: mesh.McpMeshAgent = None
) -> dict[str, Any]:
    """
    Get weather information for a specified city.

    Demonstrates self-dependency: uses own time_service capability.
    """
    city_lower = city.lower()

    if city_lower not in CITIES_DATA:
        return {
            "error": f"City '{city}' not found",
            "available_cities": list(CITIES_DATA.keys()),
            "timestamp": time_service() if time_service else "unknown"
        }

    # Simulate weather data
    temp_celsius = random.randint(-10, 40)
    condition = random.choice(WEATHER_CONDITIONS)
    humidity = random.randint(20, 95)
    wind_speed = random.randint(0, 60)

    weather_data = {
        "city": city.title(),
        "coordinates": CITIES_DATA[city_lower],
        "temperature": {
            "celsius": temp_celsius,
            "fahrenheit": round((temp_celsius * 9/5) + 32, 1)
        },
        "condition": condition,
        "humidity": f"{humidity}%",
        "wind_speed": f"{wind_speed} km/h",
        "visibility": "10 km" if condition != "foggy" else "2 km",
        "timestamp": time_service() if time_service else "unknown"
    }

    return weather_data

@app.tool()
@mesh.tool(
    capability="weather_forecast",
    dependencies=[
        "time_service",  # Self-dependency
        {
            "capability": "info",  # External dependency
            "tags": ["system", "general"]  # Smart tag matching
        }
    ],
    tags=["weather", "forecast"],
    description="Get weather forecast with system info"
)
def get_forecast(
    city: str,
    days: int = 3,
    time_service: mesh.McpMeshAgent = None,
    info: mesh.McpMeshAgent = None
) -> dict[str, Any]:
    """
    Get weather forecast for multiple days.

    Demonstrates:
    - Self-dependency (time_service)
    - External dependency (system info)
    - Smart tag-based resolution
    """
    if days < 1 or days > 7:
        days = 3

    forecast = {
        "city": city.title(),
        "forecast_days": days,
        "generated_at": time_service() if time_service else "unknown",
        "days": []
    }

    # Add system info if available
    if info:
        try:
            system_data = info()
            forecast["system_info"] = {
                "server": system_data.get("server_name", "unknown"),
                "uptime": system_data.get("uptime_formatted", "unknown")
            }
        except Exception as e:
            forecast["system_info"] = f"Error: {e}"

    # Generate forecast days
    for day in range(days):
        temp = random.randint(-5, 35)
        forecast["days"].append({
            "day": day + 1,
            "date": f"2024-01-{day + 1:02d}",
            "temperature": {
                "high": temp + random.randint(0, 10),
                "low": temp - random.randint(0, 8)
            },
            "condition": random.choice(WEATHER_CONDITIONS),
            "precipitation": f"{random.randint(0, 100)}%"
        })

    return forecast

# ===== PROMPTS with Dependencies =====

@app.prompt()
@mesh.tool(
    capability="weather_prompt",
    dependencies=["weather_data"],
    tags=["weather", "ai"],
    description="Generate weather analysis prompt"
)
def weather_analysis_prompt(
    city: str,
    analysis_type: str = "detailed",
    weather_data: mesh.McpMeshAgent = None
) -> str:
    """Generate weather analysis prompt with real data."""

    # Get current weather
    weather = {}
    if weather_data:
        try:
            weather = weather_data(city)
        except Exception as e:
            weather = {"error": str(e)}

    prompt = f"""Analyze the weather conditions for {city.title()}:

Current Weather Data:
{json.dumps(weather, indent=2)}

Analysis Type: {analysis_type}

Please provide:
1. Current conditions summary
2. Comfort level assessment
3. Activity recommendations
4. What to wear suggestions
5. Weather pattern insights

Focus on practical advice for residents and visitors."""

    return prompt

# ===== RESOURCES with Complex Dependencies =====

@app.resource("weather://config/{city}")
@mesh.tool(
    capability="weather_config",
    dependencies=["time_service"],
    tags=["weather", "config"],
    description="Weather service configuration"
)
async def weather_config(city: str, time_service: mesh.McpMeshAgent = None) -> str:
    """Weather service configuration for specific city."""

    config = {
        "service_name": "Weather Service",
        "version": "1.0.0",
        "city": city.title(),
        "capabilities": [
            "weather_data",
            "weather_forecast",
            "weather_prompt",
            "weather_config",
            "time_service"
        ],
        "features": {
            "real_time_data": False,
            "forecast_days": 7,
            "multiple_cities": True,
            "ai_analysis": True
        },
        "dependencies": {
            "internal": ["time_service"],
            "external": ["info (system.general)"]
        },
        "last_updated": time_service() if time_service else "unknown"
    }

    return json.dumps(config, indent=2)

@app.resource("weather://stats/{metric}")
@mesh.tool(
    capability="weather_stats",
    dependencies=["weather_data", "time_service"],
    tags=["weather", "metrics"],
    description="Weather service statistics"
)
async def weather_stats(
    metric: str,
    weather_data: mesh.McpMeshAgent = None,
    time_service: mesh.McpMeshAgent = None
) -> str:
    """Get weather service statistics."""

    stats = {
        "metric_type": metric,
        "service_status": "operational",
        "cities_supported": len(CITIES_DATA),
        "features_count": 5,
        "dependencies_resolved": {
            "weather_data": weather_data is not None,
            "time_service": time_service is not None
        },
        "generated_at": time_service() if time_service else "unknown"
    }

    if metric == "performance":
        stats.update({
            "avg_response_time": "150ms",
            "uptime": "99.9%",
            "requests_per_second": 42
        })
    elif metric == "usage":
        stats.update({
            "daily_requests": 1250,
            "popular_cities": ["new york", "london", "tokyo"],
            "forecast_vs_current": "60/40"
        })

    return json.dumps(stats, indent=2)

# ===== AGENT CONFIGURATION =====

@mesh.agent(
    name="weather-service",
    version="1.0.0",
    description="Advanced weather service with FastMCP and mesh integration",
    http_port=9091,
    enable_http=True,
    auto_run=True  # Zero boilerplate!
)
class WeatherService:
    """
    Weather Service Agent using dual decorator pattern.

    Features:
    - All MCP decorators: tools, prompts, resources
    - Smart dependency injection with type safety
    - Self-dependencies for internal coordination
    - External dependencies with tag-based resolution
    - Zero boilerplate - mesh handles everything
    """
    pass

# No main method needed!
# Mesh processor automatically:
# 1. Discovers the 'app' FastMCP instance
# 2. Applies dependency injection to all decorated functions
# 3. Starts HTTP server on configured port
# 4. Registers all capabilities with mesh registry
```

## Step 2: Dependencies File

Create `requirements.txt`:

```txt
mcp-mesh>=0.8,<0.9
fastmcp>=2.8.0
```

## Step 3: Documentation

Create `README.md`:

````markdown
# Weather Service Agent

Advanced weather service using MCP Mesh's dual decorator pattern.

## Features

- **All MCP Decorators**: Tools, prompts, and resources
- **Smart Dependencies**: Type-safe injection with tag-based resolution
- **Self-Dependencies**: Internal service coordination
- **Zero Boilerplate**: No main methods or manual setup

## Usage

```bash
# Start the weather service
python weather_agent.py

# Start system agent (for external dependencies)
python ../examples/simple/system_agent.py
```
````

## Testing

```bash
# Test weather data
meshctl call get_weather '{"city":"tokyo"}'

# Test forecast with dependencies
meshctl call get_forecast '{"city":"london","days":5}'
```

````

## Step 4: Testing Your Agent

### Start the Services

```bash
# Terminal 1: Start system agent (provides external dependencies)
python examples/simple/system_agent.py

# Terminal 2: Start your weather agent
python weather_agent.py
````

### Test All Features

```bash
# 1. Test basic weather data (self-dependency)
meshctl call get_weather '{"city":"tokyo"}'

# 2. Test forecast (self + external dependencies)
meshctl call get_forecast '{"city":"london","days":3}'
```

<details>
<summary>Testing prompts and resources (requires curl)</summary>

```bash
# 3. Test prompt generation
curl -s -X POST http://localhost:9091/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"prompts/get","params":{"name":"weather_analysis_prompt","arguments":{"city":"paris","analysis_type":"detailed"}}}'

# 4. Test resource access
curl -s -X POST http://localhost:9091/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"resources/read","params":{"uri":"weather://config/sydney"}}'
```

</details>

### Verify Service Integration

```bash
# Quick check - shows agent count and dependency resolution
meshctl list

# Detailed view - shows capabilities, dependencies, endpoints
meshctl status
```

## Understanding What You Built

### The Dual Decorator Pattern

Your agent demonstrates the power of MCP Mesh:

```python
@app.tool()      # ← FastMCP: Handles MCP protocol
@mesh.tool(      # ← Mesh: Adds orchestration
    capability="weather_data",
    dependencies=["time_service"]  # Smart dependency injection
)
def get_weather(city: str, time_service: mesh.McpMeshAgent = None):
    # Business logic here
```

### Key Innovations

1. **All MCP Decorators**: `@app.tool`, `@app.prompt`, `@app.resource`
2. **Smart Dependencies**: Tag-based resolution with type safety
3. **Self-Dependencies**: Internal service coordination
4. **Zero Boilerplate**: Mesh discovers `app` and handles everything

### Dependency Flow

```
Weather Agent Dependencies:
├── Internal (Self-dependencies)
│   └── time_service → get_weather_time()
├── External (Cross-service)
│   └── info (system.general) → system_agent.fetch_system_overview()
└── Automatic Resolution
    ├── Mesh finds providers
    ├── Creates type-safe proxies
    └── Injects into function parameters
```

## Advanced Patterns Demonstrated

### 1. Self-Dependencies

```python
# Agent uses its own time service
@mesh.tool(
    capability="weather_data",
    dependencies=["time_service"]  # Own capability!
)
```

### 2. Smart Tag Resolution

```python
# Gets general system info (not disk info)
dependencies=[{
    "capability": "info",
    "tags": ["system", "general"]  # Smart matching
}]
```

### 3. Type Safety

```python
# Type-safe injection
def get_forecast(
    time_service: mesh.McpMeshAgent = None,  # IDE support
    info: mesh.McpMeshAgent = None          # Type hints
):
```

### 4. Graceful Degradation

```python
# Works with or without dependencies
timestamp = time_service() if time_service else "unknown"
```

## Troubleshooting

### Service Not Starting

```bash
# Check port availability
lsof -i :9091

# Check for import errors
python -c "import mesh, fastmcp; print('Dependencies OK')"
```

### Dependencies Not Injected

```bash
# Quick check - see if all dependencies are resolved (e.g., "4/4")
meshctl list

# Detailed view - shows capabilities, resolved dependencies, and endpoints
meshctl status
```

### Function Not Found

- MCP calls use **function names**: `get_weather`
- Dependencies use **capability names**: `weather_data`
- Make sure both are correct in your decorators

## Next Steps

Congratulations! You've built a sophisticated agent using MCP Mesh. You've learned:

✅ **Dual decorator pattern** - FastMCP + Mesh orchestration
✅ **All MCP decorators** - Tools, prompts, and resources
✅ **Smart dependencies** - Type-safe injection with tags
✅ **Zero boilerplate** - Automatic service discovery and startup

### What's Next?

1. **[Local Development](../02-local-development.md)** - Set up professional dev environment
2. **[Docker Deployment](../03-docker-deployment.md)** - Containerize your agents
3. **[Kubernetes](../04-kubernetes-basics.md)** - Scale to production

### Reference Guides

- **[Mesh Decorators](../mesh-decorators.md)** - Complete decorator reference with all parameters
- **[meshctl CLI](../meshctl-cli.md)** - Command-line tool for managing agents
- **[Environment Variables](../environment-variables.md)** - Configuration options and templates

---

💡 **Key Insight**: The dual decorator pattern gives you the familiar FastMCP experience enhanced with powerful mesh orchestration!

🎯 **Pro Tip**: Use self-dependencies for internal coordination and tag-based dependencies for smart external service selection.

🚀 **Achievement Unlocked**: You've mastered the MCP Mesh dual decorator pattern! Ready for production deployment?

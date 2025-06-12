# Creating Your First Agent

> Build your own MCP Mesh agent from scratch

## Overview

In this guide, you'll create a weather service agent that:

- 🌤️ Provides weather information (simulated)
- 📊 Tracks request metrics
- 🔗 Uses dependency injection for data formatting
- 🌐 Exposes HTTP endpoints automatically
- 💾 Integrates with other agents for persistence

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

## Step 1: Basic Weather Agent

Let's start with a simple weather agent:

```python
# weather_agent.py
#!/usr/bin/env python3
"""
Weather Service Agent for MCP Mesh
Provides weather information for cities
"""

import random
from datetime import datetime
from typing import Dict, List, Optional

from mcp_mesh import mesh_agent, create_server

# Create MCP server
server = create_server("weather-agent")

# Simulated weather data
WEATHER_CONDITIONS = ["sunny", "cloudy", "rainy", "stormy", "snowy"]
CITIES_DATA = {
    "london": {"lat": 51.5074, "lon": -0.1278, "timezone": "GMT"},
    "new york": {"lat": 40.7128, "lon": -74.0060, "timezone": "EST"},
    "tokyo": {"lat": 35.6762, "lon": 139.6503, "timezone": "JST"},
    "sydney": {"lat": -33.8688, "lon": 151.2093, "timezone": "AEST"},
}


@server.tool()
@mesh_agent(
    capability="weather",
    version="1.0.0",
    description="Get current weather for a city",
    tags=["weather", "temperature", "conditions"],
    enable_http=True,
    http_port=8083
)
def weather_get_current(city: str) -> Dict[str, any]:
    """
    Get current weather for a city

    Args:
        city: City name (lowercase)

    Returns:
        Weather data including temperature, conditions, humidity
    """
    city_lower = city.lower()

    if city_lower not in CITIES_DATA:
        return {
            "error": f"City '{city}' not found",
            "available_cities": list(CITIES_DATA.keys())
        }

    # Simulate weather data
    temp_celsius = random.randint(5, 35)
    condition = random.choice(WEATHER_CONDITIONS)
    humidity = random.randint(30, 90)
    wind_speed = random.randint(5, 50)

    return {
        "city": city,
        "temperature": {
            "celsius": temp_celsius,
            "fahrenheit": (temp_celsius * 9/5) + 32
        },
        "condition": condition,
        "humidity": f"{humidity}%",
        "wind_speed": f"{wind_speed} km/h",
        "timestamp": datetime.now().isoformat(),
        "coordinates": CITIES_DATA[city_lower]
    }


@server.tool()
@mesh_agent(
    capability="weather",
    version="1.0.0",
    description="Get weather forecast",
    enable_http=True,
    http_port=8083
)
def weather_get_forecast(city: str, days: int = 5) -> Dict[str, any]:
    """
    Get weather forecast for multiple days

    Args:
        city: City name
        days: Number of days (1-7)
    """
    if days < 1 or days > 7:
        return {"error": "Days must be between 1 and 7"}

    city_lower = city.lower()
    if city_lower not in CITIES_DATA:
        return {"error": f"City '{city}' not found"}

    forecast = []
    for day in range(days):
        temp = random.randint(5, 35)
        forecast.append({
            "day": day + 1,
            "temperature": {
                "high": temp + random.randint(0, 5),
                "low": temp - random.randint(0, 5)
            },
            "condition": random.choice(WEATHER_CONDITIONS),
            "precipitation": f"{random.randint(0, 100)}%"
        })

    return {
        "city": city,
        "forecast": forecast,
        "days": days,
        "generated_at": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import os
    import logging

    # Configure logging
    logging.basicConfig(
        level=os.environ.get("MCP_MESH_LOG_LEVEL", "INFO"),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting Weather Agent...")

    # Run the server
    from mcp_mesh.server.runner import run_server
    run_server(server)
```

## Step 2: Add Dependencies

Now let's enhance our agent to use other services:

```python
# Add to weather_agent.py

# Import for type hints
from typing import Any

# Request counter for metrics
request_count = 0


@server.tool()
@mesh_agent(
    capability="weather",
    version="1.0.0",
    description="Get weather with formatting",
    dependencies=["formatter_format_json", "SystemAgent_getTime"],
    enable_http=True,
    http_port=8083
)
def weather_get_detailed(
    city: str,
    formatter_format_json: Any = None,
    SystemAgent_getTime: Any = None
) -> str:
    """
    Get detailed weather with pretty formatting

    Uses dependency injection for:
    - formatter_format_json: Pretty print JSON data
    - SystemAgent_getTime: Add current time
    """
    global request_count
    request_count += 1

    # Get weather data
    weather = weather_get_current(city)

    # Add additional details
    weather["request_id"] = request_count

    if SystemAgent_getTime:
        weather["server_time"] = SystemAgent_getTime()

    # Format the output
    if formatter_format_json:
        return formatter_format_json(weather)
    else:
        # Fallback formatting
        import json
        return json.dumps(weather, indent=2)


@server.tool()
@mesh_agent(
    capability="weather",
    version="1.0.0",
    description="Store weather history",
    dependencies=["database_save"],
    optional_dependencies=["cache_set"],
    enable_http=True,
    http_port=8083
)
def weather_record_observation(
    city: str,
    temperature: float,
    condition: str,
    database_save: Any = None,
    cache_set: Any = None
) -> Dict[str, any]:
    """
    Record a weather observation

    Dependencies:
    - database_save: Store in persistent database
    - cache_set: Cache for quick access (optional)
    """
    observation = {
        "city": city,
        "temperature": temperature,
        "condition": condition,
        "timestamp": datetime.now().isoformat(),
        "source": "manual_observation"
    }

    # Generate unique key
    key = f"weather:observation:{city}:{datetime.now().timestamp()}"

    # Save to database (required)
    if database_save:
        database_save(key, json.dumps(observation))
    else:
        return {"error": "Database service unavailable"}

    # Cache if available (optional)
    if cache_set:
        cache_key = f"weather:latest:{city}"
        cache_set(cache_key, json.dumps(observation))

    return {
        "status": "recorded",
        "key": key,
        "observation": observation,
        "cached": cache_set is not None
    }
```

## Step 3: Add Health Checks and Metrics

```python
# Add to weather_agent.py

@server.tool()
@mesh_agent(
    capability="weather",
    version="1.0.0",
    description="Health check endpoint",
    enable_http=True,
    http_port=8083,
    http_path="/health"  # Custom path
)
def weather_health() -> Dict[str, any]:
    """Health check for weather service"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "requests_served": request_count,
        "available_cities": len(CITIES_DATA),
        "timestamp": datetime.now().isoformat()
    }


@server.tool()
@mesh_agent(
    capability="weather",
    version="1.0.0",
    description="Get service metrics",
    enable_http=True,
    http_port=8083,
    http_path="/metrics"
)
def weather_metrics() -> Dict[str, any]:
    """Get weather service metrics"""
    return {
        "requests": {
            "total": request_count,
            "per_minute": request_count / max(1, (datetime.now().timestamp() - start_time) / 60)
        },
        "cities": {
            "available": list(CITIES_DATA.keys()),
            "count": len(CITIES_DATA)
        },
        "uptime_seconds": datetime.now().timestamp() - start_time,
        "version": "1.0.0"
    }

# Add at module level
start_time = datetime.now().timestamp()
```

## Step 4: Configuration and Requirements

Create the requirements file:

```txt
# requirements.txt
mcp-mesh>=1.0.0
python-dotenv>=1.0.0
```

Create a configuration file:

```python
# config.py
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Registry settings
    REGISTRY_URL = os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8000")

    # HTTP settings
    HTTP_HOST = os.getenv("MCP_MESH_HTTP_HOST", "0.0.0.0")
    HTTP_PORT = int(os.getenv("MCP_MESH_HTTP_PORT", "8083"))

    # Weather settings
    DEFAULT_CITY = os.getenv("WEATHER_DEFAULT_CITY", "london")
    CACHE_DURATION = int(os.getenv("WEATHER_CACHE_DURATION", "300"))  # seconds

    # Logging
    LOG_LEVEL = os.getenv("MCP_MESH_LOG_LEVEL", "INFO")
```

## Step 5: Running Your Agent

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Start Required Services

```bash
# Terminal 1: Registry
python -m mcp_mesh.registry.server

# Terminal 2: System Agent (if using dependencies)
cd ../examples
python system_agent.py
```

### 3. Run Your Weather Agent

```bash
# Terminal 3: Your Weather Agent
export MCP_MESH_REGISTRY_URL=http://localhost:8000
export MCP_MESH_LOG_LEVEL=INFO
python weather_agent.py

# You should see:
# INFO: Starting Weather Agent...
# INFO: Registering with registry at http://localhost:8000
# INFO: HTTP server starting on http://0.0.0.0:8083
# INFO: Agent registered successfully
```

### 4. Test Your Agent

```bash
# Get current weather
curl http://localhost:8083/weather_get_current \
  -d '{"city": "london"}'

# Get forecast
curl http://localhost:8083/weather_get_forecast \
  -d '{"city": "tokyo", "days": 3}'

# Check health
curl http://localhost:8083/health

# Get metrics
curl http://localhost:8083/metrics
```

## Step 6: Advanced Features

### 1. Add Caching

```python
# In-memory cache
weather_cache = {}

@mesh_agent(capability="weather", version="1.0.0")
def weather_get_cached(city: str) -> Dict[str, any]:
    """Get weather with caching"""
    cache_key = f"weather:{city.lower()}"

    # Check cache
    if cache_key in weather_cache:
        entry = weather_cache[cache_key]
        if datetime.now().timestamp() - entry["timestamp"] < Config.CACHE_DURATION:
            return entry["data"]

    # Cache miss - get fresh data
    data = weather_get_current(city)
    weather_cache[cache_key] = {
        "data": data,
        "timestamp": datetime.now().timestamp()
    }

    return data
```

### 2. Add Validation

```python
from pydantic import BaseModel, validator

class WeatherRequest(BaseModel):
    city: str
    units: str = "celsius"

    @validator('city')
    def city_must_be_valid(cls, v):
        if v.lower() not in CITIES_DATA:
            raise ValueError(f"Unknown city: {v}")
        return v.lower()

@mesh_agent(capability="weather", version="1.0.0")
def weather_get_validated(request: WeatherRequest) -> Dict[str, any]:
    """Get weather with input validation"""
    return weather_get_current(request.city)
```

### 3. Add Async Support

```python
import asyncio

@server.tool()
@mesh_agent(capability="weather", version="1.0.0")
async def weather_get_async(city: str) -> Dict[str, any]:
    """Async weather fetching"""
    # Simulate async operation
    await asyncio.sleep(0.1)
    return weather_get_current(city)
```

## Testing Your Agent

Create a test file:

```python
# test_weather_agent.py
import pytest
import requests

BASE_URL = "http://localhost:8083"

def test_get_current_weather():
    """Test getting current weather"""
    response = requests.post(
        f"{BASE_URL}/weather_get_current",
        json={"city": "london"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "temperature" in data
    assert "condition" in data
    assert data["city"] == "london"

def test_invalid_city():
    """Test with invalid city"""
    response = requests.post(
        f"{BASE_URL}/weather_get_current",
        json={"city": "invalid_city"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "error" in data
    assert "available_cities" in data

def test_health_check():
    """Test health endpoint"""
    response = requests.get(f"{BASE_URL}/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
```

## Packaging Your Agent

### 1. Create Dockerfile

```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MCP_MESH_REGISTRY_URL=http://mcp-mesh-registry:8000
ENV MCP_MESH_HTTP_PORT=8083

EXPOSE 8083

CMD ["python", "weather_agent.py"]
```

### 2. Create docker-compose.yml

```yaml
# docker-compose.yml
version: "3.8"

services:
  weather-agent:
    build: .
    ports:
      - "8083:8083"
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_LOG_LEVEL=INFO
    depends_on:
      - registry
    networks:
      - mcp-mesh

networks:
  mcp-mesh:
    external: true
```

## Best Practices

### 1. Error Handling

```python
@mesh_agent(capability="weather")
def weather_safe_get(city: str) -> Dict[str, any]:
    """Weather with comprehensive error handling"""
    try:
        if not city or not isinstance(city, str):
            return {"error": "Invalid city parameter"}

        result = weather_get_current(city)
        return result

    except Exception as e:
        logger.error(f"Error getting weather: {e}")
        return {
            "error": "Internal service error",
            "message": str(e),
            "city": city
        }
```

### 2. Documentation

```python
@mesh_agent(
    capability="weather",
    version="1.0.0",
    description="Production weather service",
    tags=["weather", "api", "v1"],
    metadata={
        "author": "Your Name",
        "docs": "https://docs.example.com/weather",
        "sla": "99.9%"
    }
)
def weather_documented(city: str) -> Dict[str, any]:
    """
    Get current weather conditions.

    Args:
        city: City name (case-insensitive)

    Returns:
        Dict containing:
        - temperature: Current temperature in C and F
        - condition: Weather condition string
        - humidity: Humidity percentage
        - wind_speed: Wind speed in km/h

    Raises:
        ValueError: If city is not found

    Example:
        >>> weather_documented("london")
        {"temperature": {"celsius": 18, "fahrenheit": 64}, ...}
    """
    return weather_get_current(city)
```

## Next Steps

Congratulations! You've created a fully functional MCP Mesh agent with:

- ✅ Multiple endpoints
- ✅ Dependency injection
- ✅ Health checks and metrics
- ✅ Error handling
- ✅ Testing
- ✅ Docker packaging

### Where to Go Next

1. **[Local Development](../02-local-development.md)** - Set up a professional development environment
2. **[Docker Deployment](../03-docker-deployment.md)** - Deploy multiple agents with Docker Compose
3. **[Kubernetes Deployment](../04-kubernetes-basics.md)** - Scale to Kubernetes

### Ideas for Enhancement

1. Add real weather API integration (OpenWeatherMap, etc.)
2. Implement historical weather tracking
3. Add weather alerts and notifications
4. Create a web UI for your weather service
5. Add machine learning for weather prediction

---

🎉 **Congratulations!** You've completed the Getting Started guide!

💡 **Challenge**: Extend your weather agent to use a real weather API and add a simple web interface.

## 🔧 Troubleshooting

### Development Issues

1. **Agent won't register** - Check capability name is unique and valid
2. **Dependencies not injecting** - Verify dependency services are running
3. **HTTP endpoint not accessible** - Ensure firewall allows the port
4. **Tests failing** - Start all required services before running tests
5. **Memory leaks** - Monitor with memory profiler, check for circular references

For detailed solutions, see our [Troubleshooting Guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Hot reload**: Changes to decorators require restart
- **Async complexity**: Mixing sync/async requires careful handling
- **Error propagation**: Remote errors may lose stack traces
- **Testing dependencies**: Requires running actual services or mocks
- **Code generation**: No automatic client SDK generation yet

## 📝 TODO

- [ ] Add agent template generator CLI command
- [ ] Create VSCode extension for MCP Mesh development
- [ ] Add automatic API documentation generation
- [ ] Implement contract testing framework
- [ ] Create agent marketplace/registry
- [ ] Add performance profiling decorators
- [ ] Support for streaming responses
- [ ] Add GraphQL endpoint generation

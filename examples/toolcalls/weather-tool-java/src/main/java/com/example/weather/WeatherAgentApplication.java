package com.example.weather;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

/**
 * Java Weather Tool - provides mock weather information for testing.
 *
 * <p>This agent provides a weather tool that can be discovered by LLM agents
 * using tool filtering (tags: "weather", "data", "java").
 *
 * <h2>Tools Provided</h2>
 * <ul>
 *   <li>get_weather - Get current weather for a city (mock data)</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * meshctl start examples/toolcalls/weather-tool-java -d
 *
 * # Test tools
 * meshctl list -t
 * meshctl call get_weather '{"city": "San Francisco"}'
 * </pre>
 */
@SpringBootApplication
@MeshAgent(
    name = "weather-tool-java",
    version = "1.0.0",
    description = "Weather information service providing mock conditions for testing",
    port = 9000
)
public class WeatherAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(WeatherAgentApplication.class);
    private static final Random random = new Random();

    private static final List<String> WEATHER_DESCRIPTIONS = List.of(
        "Partly cloudy with a chance of code reviews",
        "Sunny with scattered debugging sessions",
        "Clear skies, perfect for deploying",
        "Overcast with occasional stack traces",
        "Breezy with intermittent refactoring",
        "Foggy with limited visibility to production",
        "Warm front moving in from the CI/CD pipeline",
        "Light showers of pull requests expected"
    );

    public WeatherAgentApplication() {
    }

    public static void main(String[] args) {
        log.info("Starting Weather Tool (mock data)...");
        SpringApplication.run(WeatherAgentApplication.class, args);
    }

    /**
     * Get current weather for a city.
     *
     * @param city The city name (e.g., "San Francisco", "New York")
     * @return Weather information including city, temperature, description, humidity
     */
    @MeshTool(
        capability = "get_weather",
        description = "Get current weather for a city",
        tags = {"weather", "data", "java"}
    )
    public Map<String, Object> getWeather(
        @Param(value = "city", description = "City name (e.g., 'San Francisco', 'New York', 'London')") String city
    ) {
        log.info("[get_weather] Getting mock weather for city: {}", city);
        return generateMockWeather(city);
    }

    private Map<String, Object> generateMockWeather(String city) {
        int tempF = random.nextInt(76) + 5;  // 5 to 80
        int tempC = (int) Math.round((tempF - 32) * 5.0 / 9.0);
        int humidity = random.nextInt(61) + 30;  // 30 to 90
        String description = WEATHER_DESCRIPTIONS.get(random.nextInt(WEATHER_DESCRIPTIONS.size()));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("city", city);
        result.put("temperature", tempF + "F (" + tempC + "C)");
        result.put("description", description);
        result.put("humidity", humidity + "%");

        return result;
    }
}

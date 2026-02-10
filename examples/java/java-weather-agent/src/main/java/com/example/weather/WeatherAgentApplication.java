package com.example.weather;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Java Weather Agent - provides mock weather information for testing.
 *
 * <p>This agent provides weather tools that can be discovered by LLM agents
 * using tool filtering (tags: "tools", "weather").
 *
 * <h2>Tools Provided</h2>
 * <ul>
 *   <li>get_weather_by_city - Get current weather for a city</li>
 *   <li>get_weather_by_zip - Get current weather for a US zip code</li>
 *   <li>get_forecast - Get 3-day weather forecast for a city</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * meshctl start examples/java/java-weather-agent -d
 *
 * # Test tools
 * meshctl list -t
 * meshctl call getWeatherByCity '{"city": "San Francisco"}'
 * meshctl call getWeatherByZip '{"zip_code": "94102"}'
 * </pre>
 */
@SpringBootApplication
@MeshAgent(
    name = "java-weather-agent",
    version = "1.0.0",
    description = "Weather information service providing mock conditions and forecasts for testing",
    port = 9012
)
public class WeatherAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(WeatherAgentApplication.class);

    public WeatherAgentApplication() {
    }

    public static void main(String[] args) {
        log.info("Starting Weather Agent (using mock data)...");
        SpringApplication.run(WeatherAgentApplication.class, args);
    }

    /**
     * Get current weather for a city.
     *
     * @param city The city name (e.g., "San Francisco", "New York")
     * @return Weather information including temperature, conditions, humidity
     */
    @MeshTool(
        capability = "get_weather_by_city",
        description = "Get current weather conditions for a city. Returns temperature, conditions, humidity, and wind speed.",
        tags = {"tools", "data", "weather", "city"}
    )
    public Map<String, Object> getWeatherByCity(
        @Param(value = "city", description = "City name (e.g., 'San Francisco', 'New York', 'London')") String city
    ) {
        log.info("[get_weather_by_city] Getting weather for city: {}", city);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("location", city);
        result.put("region", "Mock Region");
        result.put("country", "Mockland");
        result.put("temperature_f", 72);
        result.put("temperature_c", 22);
        result.put("feels_like_f", 70);
        result.put("feels_like_c", 21);
        result.put("conditions", "Partly cloudy");
        result.put("humidity", 65);
        result.put("wind_mph", 8);
        result.put("wind_direction", "NW");
        result.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        result.put("source", "mock");

        return result;
    }

    /**
     * Get current weather for a US zip code.
     *
     * @param zipCode The US zip code (e.g., "94102", "10001")
     * @return Weather information including temperature, conditions, humidity
     */
    @MeshTool(
        capability = "get_weather_by_zip",
        description = "Get current weather conditions for a US zip code. Returns temperature, conditions, humidity, and wind speed.",
        tags = {"tools", "data", "weather", "zipcode"}
    )
    public Map<String, Object> getWeatherByZip(
        @Param(value = "zip_code", description = "US zip code (e.g., '94102', '10001', '90210')") String zipCode
    ) {
        log.info("[get_weather_by_zip] Getting weather for zip: {}", zipCode);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("location", "Zip " + zipCode);
        result.put("zip_code", zipCode);
        result.put("region", "Mock Region");
        result.put("country", "Mockland");
        result.put("temperature_f", 68);
        result.put("temperature_c", 20);
        result.put("feels_like_f", 70);
        result.put("feels_like_c", 21);
        result.put("conditions", "Partly cloudy");
        result.put("humidity", 65);
        result.put("wind_mph", 8);
        result.put("wind_direction", "NW");
        result.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        result.put("source", "mock");

        return result;
    }

    /**
     * Get 3-day weather forecast for a city.
     *
     * @param city The city name
     * @return 3-day forecast with daily high/low temperatures and conditions
     */
    @MeshTool(
        capability = "get_forecast",
        description = "Get 3-day weather forecast for a city. Returns daily high/low temperatures and conditions.",
        tags = {"tools", "data", "weather", "forecast"}
    )
    public Map<String, Object> getForecast(
        @Param(value = "city", description = "City name for forecast") String city
    ) {
        log.info("[get_forecast] Getting 3-day forecast for: {}", city);

        Map<String, Object> day1 = new LinkedHashMap<>();
        day1.put("day", "Today");
        day1.put("date", "2025-03-15");
        day1.put("high_f", 75);
        day1.put("low_f", 60);
        day1.put("high_c", 24);
        day1.put("low_c", 16);
        day1.put("conditions", "Sunny");
        day1.put("chance_of_rain", "10%");

        Map<String, Object> day2 = new LinkedHashMap<>();
        day2.put("day", "Tomorrow");
        day2.put("date", "2025-03-16");
        day2.put("high_f", 70);
        day2.put("low_f", 55);
        day2.put("high_c", 21);
        day2.put("low_c", 13);
        day2.put("conditions", "Partly cloudy");
        day2.put("chance_of_rain", "30%");

        Map<String, Object> day3 = new LinkedHashMap<>();
        day3.put("day", "Day After");
        day3.put("date", "2025-03-17");
        day3.put("high_f", 65);
        day3.put("low_f", 50);
        day3.put("high_c", 18);
        day3.put("low_c", 10);
        day3.put("conditions", "Light rain");
        day3.put("chance_of_rain", "70%");

        @SuppressWarnings("unchecked")
        Map<String, Object>[] forecast = new Map[]{day1, day2, day3};

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("location", city);
        result.put("forecast", forecast);
        result.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        result.put("source", "mock");

        return result;
    }
}

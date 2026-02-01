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
import java.util.Map;
import java.util.Random;

/**
 * Java Weather Agent - provides weather information tools.
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
 * cd examples/java/java-weather-agent
 * MESH_NATIVE_LIB_PATH=/path/to/native/libs mvn spring-boot:run
 *
 * # Test tools
 * meshctl list -t
 * meshctl call get_weather_by_city '{"city": "San Francisco"}'
 * meshctl call get_weather_by_zip '{"zip_code": "94102"}'
 * </pre>
 */
@SpringBootApplication
@MeshAgent(
    name = "java-weather-agent",
    version = "1.0.0",
    description = "Weather information service providing current conditions and forecasts",
    port = 9012
)
public class WeatherAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(WeatherAgentApplication.class);
    private static final Random random = new Random();

    public static void main(String[] args) {
        log.info("Starting Weather Agent...");
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

        // Generate realistic mock weather data based on city
        WeatherData weather = generateWeatherForCity(city);

        return Map.of(
            "city", city,
            "temperature_f", weather.temperatureF,
            "temperature_c", weather.temperatureC,
            "conditions", weather.conditions,
            "humidity", weather.humidity,
            "wind_mph", weather.windMph,
            "timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME),
            "source", "java-weather-agent"
        );
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

        // Map zip code to city for mock data
        String city = zipToCity(zipCode);
        WeatherData weather = generateWeatherForCity(city);

        return Map.of(
            "zip_code", zipCode,
            "city", city,
            "temperature_f", weather.temperatureF,
            "temperature_c", weather.temperatureC,
            "conditions", weather.conditions,
            "humidity", weather.humidity,
            "wind_mph", weather.windMph,
            "timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME),
            "source", "java-weather-agent"
        );
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

        WeatherData today = generateWeatherForCity(city);
        int baseTemp = today.temperatureF;

        return Map.of(
            "city", city,
            "forecast", new Map[] {
                Map.of(
                    "day", "Today",
                    "high_f", baseTemp + random.nextInt(5),
                    "low_f", baseTemp - 10 - random.nextInt(5),
                    "conditions", today.conditions
                ),
                Map.of(
                    "day", "Tomorrow",
                    "high_f", baseTemp + random.nextInt(8) - 2,
                    "low_f", baseTemp - 12 - random.nextInt(5),
                    "conditions", randomCondition()
                ),
                Map.of(
                    "day", "Day After",
                    "high_f", baseTemp + random.nextInt(10) - 3,
                    "low_f", baseTemp - 14 - random.nextInt(5),
                    "conditions", randomCondition()
                )
            },
            "timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME),
            "source", "java-weather-agent"
        );
    }

    // =========================================================================
    // Mock data generation
    // =========================================================================

    private record WeatherData(
        int temperatureF,
        int temperatureC,
        String conditions,
        int humidity,
        int windMph
    ) {}

    private WeatherData generateWeatherForCity(String city) {
        // Generate somewhat realistic weather based on city name hash
        int hash = Math.abs(city.toLowerCase().hashCode());
        int baseTemp = 50 + (hash % 40); // 50-90F range

        // Add some randomness
        int tempF = baseTemp + random.nextInt(10) - 5;
        int tempC = (tempF - 32) * 5 / 9;

        String[] conditions = {"Sunny", "Partly Cloudy", "Cloudy", "Light Rain", "Clear", "Overcast"};
        String condition = conditions[hash % conditions.length];

        int humidity = 30 + (hash % 50) + random.nextInt(10);
        int windMph = 5 + (hash % 15) + random.nextInt(5);

        return new WeatherData(tempF, tempC, condition, humidity, windMph);
    }

    private String zipToCity(String zipCode) {
        // Map common zip codes to cities
        return switch (zipCode) {
            case "94102", "94103", "94104" -> "San Francisco";
            case "10001", "10002", "10003" -> "New York";
            case "90210", "90211" -> "Beverly Hills";
            case "60601", "60602" -> "Chicago";
            case "98101", "98102" -> "Seattle";
            case "02101", "02102" -> "Boston";
            case "33101", "33102" -> "Miami";
            case "78201", "78202" -> "San Antonio";
            case "85001", "85002" -> "Phoenix";
            case "19101", "19102" -> "Philadelphia";
            default -> "Unknown City (Zip: " + zipCode + ")";
        };
    }

    private String randomCondition() {
        String[] conditions = {"Sunny", "Partly Cloudy", "Cloudy", "Light Rain", "Clear", "Overcast", "Scattered Showers"};
        return conditions[random.nextInt(conditions.length)];
    }
}

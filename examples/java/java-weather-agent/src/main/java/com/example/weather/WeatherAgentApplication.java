package com.example.weather;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Java Weather Agent - provides real weather information from wttr.in API.
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
    description = "Weather information service providing current conditions and forecasts from wttr.in",
    port = 9012
)
public class WeatherAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(WeatherAgentApplication.class);
    private static final String WTTR_BASE_URL = "https://wttr.in";

    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper;

    public WeatherAgentApplication() {
        // Configure RestTemplate with timeouts
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(10000);  // 10 seconds
        factory.setReadTimeout(30000);     // 30 seconds
        this.restTemplate = new RestTemplate(factory);
        this.objectMapper = new ObjectMapper();
    }

    public static void main(String[] args) {
        log.info("Starting Weather Agent (using wttr.in API)...");
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

        try {
            JsonNode weatherData = fetchWeather(city);
            return parseCurrentWeather(city, weatherData);
        } catch (Exception e) {
            log.error("Failed to fetch weather for {}: {}", city, e.getMessage());
            return errorResponse(city, e.getMessage());
        }
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

        try {
            // wttr.in supports zip codes directly
            JsonNode weatherData = fetchWeather(zipCode);
            Map<String, Object> result = parseCurrentWeather(zipCode, weatherData);
            result.put("zip_code", zipCode);
            return result;
        } catch (Exception e) {
            log.error("Failed to fetch weather for zip {}: {}", zipCode, e.getMessage());
            return errorResponse(zipCode, e.getMessage());
        }
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

        try {
            JsonNode weatherData = fetchWeather(city);
            return parseForecast(city, weatherData);
        } catch (Exception e) {
            log.error("Failed to fetch forecast for {}: {}", city, e.getMessage());
            return errorResponse(city, e.getMessage());
        }
    }

    // =========================================================================
    // wttr.in API integration
    // =========================================================================

    private JsonNode fetchWeather(String location) throws Exception {
        String encodedLocation = URLEncoder.encode(location, StandardCharsets.UTF_8);
        String url = WTTR_BASE_URL + "/" + encodedLocation + "?format=j1";

        log.debug("Fetching weather from: {}", url);

        String response = restTemplate.getForObject(url, String.class);
        return objectMapper.readTree(response);
    }

    private Map<String, Object> parseCurrentWeather(String location, JsonNode data) {
        JsonNode current = data.path("current_condition").get(0);
        JsonNode nearest = data.path("nearest_area").get(0);

        // Get location info
        String areaName = nearest.path("areaName").get(0).path("value").asText(location);
        String country = nearest.path("country").get(0).path("value").asText("");
        String region = nearest.path("region").get(0).path("value").asText("");

        // Get weather data
        int tempF = current.path("temp_F").asInt();
        int tempC = current.path("temp_C").asInt();
        int humidity = current.path("humidity").asInt();
        int windMph = current.path("windspeedMiles").asInt();
        String windDir = current.path("winddir16Point").asText();
        int feelsLikeF = current.path("FeelsLikeF").asInt();
        int feelsLikeC = current.path("FeelsLikeC").asInt();

        // Get weather description
        String conditions = current.path("weatherDesc").get(0).path("value").asText("Unknown");

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("location", areaName);
        result.put("region", region);
        result.put("country", country);
        result.put("temperature_f", tempF);
        result.put("temperature_c", tempC);
        result.put("feels_like_f", feelsLikeF);
        result.put("feels_like_c", feelsLikeC);
        result.put("conditions", conditions);
        result.put("humidity", humidity);
        result.put("wind_mph", windMph);
        result.put("wind_direction", windDir);
        result.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        result.put("source", "wttr.in");

        return result;
    }

    private Map<String, Object> parseForecast(String location, JsonNode data) {
        JsonNode nearest = data.path("nearest_area").get(0);
        String areaName = nearest.path("areaName").get(0).path("value").asText(location);

        JsonNode weatherArray = data.path("weather");

        Map<String, Object>[] forecast = new Map[Math.min(3, weatherArray.size())];
        String[] dayNames = {"Today", "Tomorrow", "Day After"};

        for (int i = 0; i < forecast.length; i++) {
            JsonNode day = weatherArray.get(i);

            int maxTempF = day.path("maxtempF").asInt();
            int minTempF = day.path("mintempF").asInt();
            int maxTempC = day.path("maxtempC").asInt();
            int minTempC = day.path("mintempC").asInt();
            String date = day.path("date").asText();

            // Get average condition from hourly data
            JsonNode hourly = day.path("hourly");
            String conditions = hourly.get(hourly.size() / 2).path("weatherDesc").get(0).path("value").asText("Unknown");
            int chanceOfRain = hourly.get(hourly.size() / 2).path("chanceofrain").asInt();

            Map<String, Object> dayForecast = new LinkedHashMap<>();
            dayForecast.put("day", dayNames[i]);
            dayForecast.put("date", date);
            dayForecast.put("high_f", maxTempF);
            dayForecast.put("low_f", minTempF);
            dayForecast.put("high_c", maxTempC);
            dayForecast.put("low_c", minTempC);
            dayForecast.put("conditions", conditions);
            dayForecast.put("chance_of_rain", chanceOfRain + "%");

            forecast[i] = dayForecast;
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("location", areaName);
        result.put("forecast", forecast);
        result.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        result.put("source", "wttr.in");

        return result;
    }

    private Map<String, Object> errorResponse(String location, String error) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("location", location);
        result.put("error", error);
        result.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        result.put("source", "java-weather-agent");
        return result;
    }
}

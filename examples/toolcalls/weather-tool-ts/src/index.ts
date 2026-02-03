#!/usr/bin/env npx tsx
/**
 * weather-tool-ts - MCP Mesh Agent
 *
 * A MCP Mesh agent that provides weather information from wttr.in API.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "WeatherToolTs Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "weather-tool-ts",
  httpPort: 9000,
});

// Weather response type
interface WeatherResult {
  city: string;
  temperature: string;
  description: string;
  humidity: string;
}

// Creative weather descriptions
const weatherDescriptions = [
  "Partly cloudy with a chance of code reviews",
  "Sunny with scattered debugging sessions",
  "Clear skies, perfect for deploying",
  "Overcast with occasional stack traces",
  "Mild with intermittent pull requests",
  "Breezy with a high chance of refactoring",
  "Foggy, visibility limited to one sprint",
  "Warm and ideal for pair programming",
];

// Helper to get random integer between min and max (inclusive)
function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

// Helper to convert Fahrenheit to Celsius
function fahrenheitToCelsius(f: number): number {
  return Math.round((f - 32) * 5 / 9);
}

// ===== TOOLS =====

agent.addTool({
  name: "get_weather",
  capability: "get_weather",
  description: "Get current weather for a city",
  tags: ["weather", "data", "typescript"],
  parameters: z.object({
    city: z.string().describe("The city name (e.g., 'San Francisco', 'New York', 'London')"),
  }),
  execute: async (args): Promise<WeatherResult> => {
    // Generate mock weather data
    const tempF = randomInt(5, 80);
    const tempC = fahrenheitToCelsius(tempF);
    const humidity = randomInt(30, 90);
    const description = weatherDescriptions[randomInt(0, weatherDescriptions.length - 1)];

    return {
      city: args.city,
      temperature: `${tempF}F (${tempC}C)`,
      description: description,
      humidity: `${humidity}%`,
    };
  },
});

console.log("weather-tool-ts agent defined. Waiting for auto-start...");

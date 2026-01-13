/**
 * Unit tests for provider-handler-registry.ts
 *
 * Tests the ProviderHandlerRegistry singleton that manages vendor-specific handlers.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import type { ProviderHandler, VendorCapabilities, OutputMode, OutputSchema, ToolSchema, PreparedRequest } from "../provider-handlers/provider-handler.js";
import { ProviderHandlerRegistry } from "../provider-handlers/provider-handler-registry.js";
import { ClaudeHandler } from "../provider-handlers/claude-handler.js";

// Import handlers to register them (side effect registration)
import "../provider-handlers/openai-handler.js";
import "../provider-handlers/generic-handler.js";

describe("ProviderHandlerRegistry", () => {
  beforeEach(() => {
    // Clear cache before each test to ensure clean state
    ProviderHandlerRegistry.clearCache();
  });

  describe("getHandler", () => {
    it("should return ClaudeHandler for anthropic vendor", () => {
      const handler = ProviderHandlerRegistry.getHandler("anthropic");

      expect(handler).toBeDefined();
      expect(handler.vendor).toBe("anthropic");
      expect(handler.constructor.name).toBe("ClaudeHandler");
    });

    it("should return OpenAIHandler for openai vendor", () => {
      const handler = ProviderHandlerRegistry.getHandler("openai");

      expect(handler).toBeDefined();
      expect(handler.vendor).toBe("openai");
      expect(handler.constructor.name).toBe("OpenAIHandler");
    });

    it("should return GenericHandler for unknown vendor", () => {
      const handler = ProviderHandlerRegistry.getHandler("unknown");

      expect(handler).toBeDefined();
      expect(handler.constructor.name).toBe("GenericHandler");
    });

    it("should return GenericHandler for null vendor", () => {
      const handler = ProviderHandlerRegistry.getHandler(null);

      expect(handler).toBeDefined();
      expect(handler.constructor.name).toBe("GenericHandler");
    });

    it("should return GenericHandler for undefined vendor", () => {
      const handler = ProviderHandlerRegistry.getHandler(undefined);

      expect(handler).toBeDefined();
      expect(handler.constructor.name).toBe("GenericHandler");
    });

    it("should return GenericHandler for unregistered vendor", () => {
      const handler = ProviderHandlerRegistry.getHandler("some-custom-vendor");

      expect(handler).toBeDefined();
      expect(handler.constructor.name).toBe("GenericHandler");
    });

    it("should normalize vendor name to lowercase", () => {
      const handler1 = ProviderHandlerRegistry.getHandler("ANTHROPIC");
      const handler2 = ProviderHandlerRegistry.getHandler("Anthropic");
      const handler3 = ProviderHandlerRegistry.getHandler("anthropic");

      expect(handler1.vendor).toBe("anthropic");
      expect(handler2.vendor).toBe("anthropic");
      expect(handler3.vendor).toBe("anthropic");
    });

    it("should trim whitespace from vendor name", () => {
      const handler = ProviderHandlerRegistry.getHandler("  openai  ");

      expect(handler.vendor).toBe("openai");
    });

    it("should cache handler instances (singleton per vendor)", () => {
      const handler1 = ProviderHandlerRegistry.getHandler("anthropic");
      const handler2 = ProviderHandlerRegistry.getHandler("anthropic");

      expect(handler1).toBe(handler2);
    });

    it("should return different instances for different vendors", () => {
      const anthropicHandler = ProviderHandlerRegistry.getHandler("anthropic");
      const openaiHandler = ProviderHandlerRegistry.getHandler("openai");

      expect(anthropicHandler).not.toBe(openaiHandler);
    });
  });

  describe("register", () => {
    afterEach(() => {
      // Restore original ClaudeHandler after tests that may override it
      ProviderHandlerRegistry.register("anthropic", ClaudeHandler);
      ProviderHandlerRegistry.clearCache();
    });

    it("should register custom handler", () => {
      class CustomHandler implements ProviderHandler {
        readonly vendor = "custom";

        prepareRequest(messages: unknown[]): PreparedRequest {
          return { messages: messages as PreparedRequest["messages"] };
        }

        formatSystemPrompt(basePrompt: string): string {
          return basePrompt;
        }

        getCapabilities(): VendorCapabilities {
          return {
            nativeToolCalling: false,
            structuredOutput: false,
            streaming: false,
            vision: false,
            jsonMode: false,
          };
        }

        determineOutputMode(): OutputMode {
          return "text";
        }
      }

      ProviderHandlerRegistry.register("custom", CustomHandler);
      const handler = ProviderHandlerRegistry.getHandler("custom");

      expect(handler).toBeDefined();
      expect(handler.vendor).toBe("custom");
      expect(handler.constructor.name).toBe("CustomHandler");
    });

    it("should clear cached instance when re-registering", () => {
      // Get initial handler
      const handler1 = ProviderHandlerRegistry.getHandler("anthropic");

      // Register a new handler for the same vendor
      class ReplacementHandler implements ProviderHandler {
        readonly vendor = "anthropic";

        prepareRequest(messages: unknown[]): PreparedRequest {
          return { messages: messages as PreparedRequest["messages"] };
        }

        formatSystemPrompt(basePrompt: string): string {
          return basePrompt;
        }

        getCapabilities(): VendorCapabilities {
          return {
            nativeToolCalling: false,
            structuredOutput: false,
            streaming: false,
            vision: false,
            jsonMode: false,
          };
        }

        determineOutputMode(): OutputMode {
          return "text";
        }
      }

      ProviderHandlerRegistry.register("anthropic", ReplacementHandler);
      const handler2 = ProviderHandlerRegistry.getHandler("anthropic");

      expect(handler2.constructor.name).toBe("ReplacementHandler");
      expect(handler1).not.toBe(handler2);
    });
  });

  describe("listVendors", () => {
    it("should list registered vendors", () => {
      const vendors = ProviderHandlerRegistry.listVendors();

      expect(vendors.has("anthropic")).toBe(true);
      expect(vendors.has("openai")).toBe(true);
      expect(vendors.get("anthropic")).toBe("ClaudeHandler");
      expect(vendors.get("openai")).toBe("OpenAIHandler");
    });
  });

  describe("hasHandler", () => {
    it("should return true for registered vendors", () => {
      expect(ProviderHandlerRegistry.hasHandler("anthropic")).toBe(true);
      expect(ProviderHandlerRegistry.hasHandler("openai")).toBe(true);
    });

    it("should return false for unregistered vendors", () => {
      expect(ProviderHandlerRegistry.hasHandler("unregistered")).toBe(false);
      expect(ProviderHandlerRegistry.hasHandler("cohere")).toBe(false);
    });

    it("should normalize vendor name for lookup", () => {
      expect(ProviderHandlerRegistry.hasHandler("ANTHROPIC")).toBe(true);
      expect(ProviderHandlerRegistry.hasHandler("  openai  ")).toBe(true);
    });
  });

  describe("clearCache", () => {
    it("should clear all cached instances", () => {
      // Get handlers to populate cache
      const handler1 = ProviderHandlerRegistry.getHandler("anthropic");
      const handler2 = ProviderHandlerRegistry.getHandler("openai");

      // Clear cache
      ProviderHandlerRegistry.clearCache();

      // Get handlers again - should be new instances
      const handler3 = ProviderHandlerRegistry.getHandler("anthropic");
      const handler4 = ProviderHandlerRegistry.getHandler("openai");

      expect(handler1).not.toBe(handler3);
      expect(handler2).not.toBe(handler4);
    });
  });
});

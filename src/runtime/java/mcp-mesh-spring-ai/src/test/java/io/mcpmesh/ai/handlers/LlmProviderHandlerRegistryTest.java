package io.mcpmesh.ai.handlers;

import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.*;

/**
 * Tests for {@link LlmProviderHandlerRegistry}.
 *
 * <p>Validates handler lookup, vendor normalization, alias resolution,
 * caching behavior, vendor extraction from model strings, and vendor listing.
 *
 * <p>IMPORTANT: The registry uses static state. Each test clears the cache
 * via {@link LlmProviderHandlerRegistry#clearCache()} to ensure isolation.
 */
class LlmProviderHandlerRegistryTest {

    @BeforeEach
    void setUp() {
        LlmProviderHandlerRegistry.clearCache();
    }

    @Nested
    @DisplayName("getHandler")
    class GetHandlerTests {

        @Test
        @DisplayName("'anthropic' returns AnthropicHandler")
        void anthropic_returnsAnthropicHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("anthropic");
            assertEquals("anthropic", handler.getVendor());
            assertTrue(handler instanceof AnthropicHandler);
        }

        @Test
        @DisplayName("'openai' returns OpenAiHandler")
        void openai_returnsOpenAiHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("openai");
            assertEquals("openai", handler.getVendor());
            assertTrue(handler instanceof OpenAiHandler);
        }

        @Test
        @DisplayName("'gemini' returns GeminiHandler")
        void gemini_returnsGeminiHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("gemini");
            assertEquals("gemini", handler.getVendor());
            assertTrue(handler instanceof GeminiHandler);
        }

        @Test
        @DisplayName("'unknown' returns GenericHandler")
        void unknown_returnsGenericHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("unknown");
            assertEquals("generic", handler.getVendor());
            assertTrue(handler instanceof GenericHandler);
        }

        @Test
        @DisplayName("null returns GenericHandler")
        void null_returnsGenericHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler(null);
            assertEquals("generic", handler.getVendor());
            assertTrue(handler instanceof GenericHandler);
        }

        @Test
        @DisplayName("empty string returns GenericHandler")
        void empty_returnsGenericHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("");
            assertEquals("generic", handler.getVendor());
            assertTrue(handler instanceof GenericHandler);
        }
    }

    @Nested
    @DisplayName("Vendor Normalization")
    class VendorNormalizationTests {

        @Test
        @DisplayName("'ANTHROPIC' (uppercase) returns AnthropicHandler")
        void uppercase_returnsCorrectHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("ANTHROPIC");
            assertTrue(handler instanceof AnthropicHandler);
        }

        @Test
        @DisplayName("'Anthropic' (mixed case) returns AnthropicHandler")
        void mixedCase_returnsCorrectHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("Anthropic");
            assertTrue(handler instanceof AnthropicHandler);
        }

        @Test
        @DisplayName("'  openai  ' (whitespace) returns OpenAiHandler")
        void whitespace_returnsCorrectHandler() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("  openai  ");
            assertTrue(handler instanceof OpenAiHandler);
        }
    }

    @Nested
    @DisplayName("Alias Lookup")
    class AliasLookupTests {

        @Test
        @DisplayName("'claude' resolves to AnthropicHandler")
        void claude_resolvesToAnthropic() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("claude");
            assertTrue(handler instanceof AnthropicHandler);
            assertEquals("anthropic", handler.getVendor());
        }

        @Test
        @DisplayName("'gpt' resolves to OpenAiHandler")
        void gpt_resolvesToOpenAi() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("gpt");
            assertTrue(handler instanceof OpenAiHandler);
            assertEquals("openai", handler.getVendor());
        }

        @Test
        @DisplayName("'google' resolves to GeminiHandler")
        void google_resolvesToGemini() {
            LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("google");
            assertTrue(handler instanceof GeminiHandler);
            assertEquals("gemini", handler.getVendor());
        }
    }

    @Nested
    @DisplayName("Caching")
    class CachingTests {

        @Test
        @DisplayName("same instance returned for same vendor")
        void sameVendor_returnsSameInstance() {
            LlmProviderHandler first = LlmProviderHandlerRegistry.getHandler("anthropic");
            LlmProviderHandler second = LlmProviderHandlerRegistry.getHandler("anthropic");
            assertSame(first, second, "Should return cached instance for same vendor");
        }

        @Test
        @DisplayName("different instances for different vendors")
        void differentVendors_returnDifferentInstances() {
            LlmProviderHandler anthropic = LlmProviderHandlerRegistry.getHandler("anthropic");
            LlmProviderHandler openai = LlmProviderHandlerRegistry.getHandler("openai");
            assertNotSame(anthropic, openai, "Different vendors should return different instances");
        }
    }

    @Nested
    @DisplayName("clearCache")
    class ClearCacheTests {

        @Test
        @DisplayName("after clearCache, new instances are returned")
        void clearCache_returnsNewInstances() {
            LlmProviderHandler before = LlmProviderHandlerRegistry.getHandler("anthropic");
            LlmProviderHandlerRegistry.clearCache();
            LlmProviderHandler after = LlmProviderHandlerRegistry.getHandler("anthropic");
            assertNotSame(before, after, "Should return new instance after cache clear");
        }
    }

    @Nested
    @DisplayName("extractVendor")
    class ExtractVendorTests {

        @Test
        @DisplayName("'anthropic/claude-sonnet-4-5' extracts 'anthropic'")
        void explicitPrefix_anthropic() {
            assertEquals("anthropic", LlmProviderHandlerRegistry.extractVendor("anthropic/claude-sonnet-4-5"));
        }

        @Test
        @DisplayName("'openai/gpt-4' extracts 'openai'")
        void explicitPrefix_openai() {
            assertEquals("openai", LlmProviderHandlerRegistry.extractVendor("openai/gpt-4"));
        }

        @Test
        @DisplayName("'claude-sonnet-4-5' infers 'anthropic'")
        void inferredFromClaude() {
            assertEquals("anthropic", LlmProviderHandlerRegistry.extractVendor("claude-sonnet-4-5"));
        }

        @Test
        @DisplayName("'gpt-4' infers 'openai'")
        void inferredFromGpt() {
            assertEquals("openai", LlmProviderHandlerRegistry.extractVendor("gpt-4"));
        }

        @Test
        @DisplayName("'gemini-3-flash' infers 'gemini'")
        void inferredFromGemini() {
            assertEquals("gemini", LlmProviderHandlerRegistry.extractVendor("gemini-3-flash"));
        }

        @Test
        @DisplayName("null returns 'unknown'")
        void null_returnsUnknown() {
            assertEquals("unknown", LlmProviderHandlerRegistry.extractVendor(null));
        }

        @Test
        @DisplayName("empty string returns 'unknown'")
        void empty_returnsUnknown() {
            assertEquals("unknown", LlmProviderHandlerRegistry.extractVendor(""));
        }

        @Test
        @DisplayName("'o1-preview' infers 'openai' (starts with o1)")
        void o1Model_infersOpenAi() {
            assertEquals("openai", LlmProviderHandlerRegistry.extractVendor("o1-preview"));
        }
    }

    @Nested
    @DisplayName("hasHandler")
    class HasHandlerTests {

        @Test
        @DisplayName("true for registered vendors: anthropic, openai, gemini")
        void registeredVendors_returnTrue() {
            assertTrue(LlmProviderHandlerRegistry.hasHandler("anthropic"));
            assertTrue(LlmProviderHandlerRegistry.hasHandler("openai"));
            assertTrue(LlmProviderHandlerRegistry.hasHandler("gemini"));
        }

        @Test
        @DisplayName("false for unregistered vendors")
        void unregisteredVendors_returnFalse() {
            assertFalse(LlmProviderHandlerRegistry.hasHandler("unregistered"));
            assertFalse(LlmProviderHandlerRegistry.hasHandler("cohere"));
        }

        @Test
        @DisplayName("case-insensitive: 'ANTHROPIC' returns true")
        void caseInsensitive_returnsTrue() {
            assertTrue(LlmProviderHandlerRegistry.hasHandler("ANTHROPIC"));
        }

        @Test
        @DisplayName("whitespace trimmed: '  openai  ' returns true")
        void whitespace_returnsTrue() {
            assertTrue(LlmProviderHandlerRegistry.hasHandler("  openai  "));
        }

        @Test
        @DisplayName("null returns false")
        void null_returnsFalse() {
            assertFalse(LlmProviderHandlerRegistry.hasHandler(null));
        }

        @Test
        @DisplayName("empty string returns false")
        void empty_returnsFalse() {
            assertFalse(LlmProviderHandlerRegistry.hasHandler(""));
        }
    }

    @Nested
    @DisplayName("listVendors")
    class ListVendorsTests {

        @Test
        @DisplayName("returns all registered vendor-to-handler mappings")
        void returnsAllMappings() {
            Map<String, String> vendors = LlmProviderHandlerRegistry.listVendors();
            assertFalse(vendors.isEmpty(), "Vendor list should not be empty");
        }

        @Test
        @DisplayName("contains primary vendors with correct handler names")
        void containsPrimaryVendors() {
            Map<String, String> vendors = LlmProviderHandlerRegistry.listVendors();
            assertEquals("AnthropicHandler", vendors.get("anthropic"));
            assertEquals("OpenAiHandler", vendors.get("openai"));
            assertEquals("GeminiHandler", vendors.get("gemini"));
        }

        @Test
        @DisplayName("contains alias entries with correct handler names")
        void containsAliasEntries() {
            Map<String, String> vendors = LlmProviderHandlerRegistry.listVendors();
            assertEquals("AnthropicHandler", vendors.get("claude"));
            assertEquals("OpenAiHandler", vendors.get("gpt"));
            assertEquals("GeminiHandler", vendors.get("google"));
        }
    }
}

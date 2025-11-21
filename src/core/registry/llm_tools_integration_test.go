package registry

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/registry/generated"
)

// TestLLMToolsInHeartbeatResponse tests that llm_tools are returned in heartbeat response
func TestLLMToolsInHeartbeatResponse(t *testing.T) {
	gin.SetMode(gin.TestMode)

	t.Run("ReturnLLMToolsForAgentWithLLMFilter", func(t *testing.T) {
		// Setup test environment
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// Step 1: Register a tool provider agent with input_schema
		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
		providerAgent := generated.MeshAgentRegistration{
			AgentId:   "pdf-provider",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "extract_pdf",
					Capability:   "pdf_extractor",
					Description:  stringPtr("Extract text from PDF files"),
					Version:      stringPtr("1.0.0"),
					Tags:         &[]string{"document", "pdf", "advanced"},
					InputSchema: &map[string]interface{}{
						"type": "object",
						"properties": map[string]interface{}{
							"file_path": map[string]interface{}{"type": "string"},
						},
						"required": []string{"file_path"},
					},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(8080),
		}

		jsonData, err := json.Marshal(providerAgent)
		require.NoError(t, err)
		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		// Step 2: Register an LLM agent with llm_filter that references the pdf tool
		llmAgentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
		llmAgent := generated.MeshAgentRegistration{
			AgentId:   "claude-agent",
			AgentType: &llmAgentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "chat",
					Capability:   "chat",
					Description:  stringPtr("Chat with Claude"),
					InputSchema: &map[string]interface{}{
						"type": "object",
						"properties": map[string]interface{}{
							"message": map[string]interface{}{"type": "string"},
						},
						"required": []string{"message"},
					},
					LlmFilter: &map[string]interface{}{
						"filter": []interface{}{
							map[string]interface{}{
								"capability": "pdf_extractor",
								"tags":       []string{"document", "pdf"},
							},
						},
						"filter_mode":  "all",
						"inject_param": "llm_tools",
					},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(8081),
		}

		jsonData, err = json.Marshal(llmAgent)
		require.NoError(t, err)
		req, err = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)

		// Assert successful response
		assert.Equal(t, http.StatusOK, recorder.Code)

		var response generated.MeshRegistrationResponse
		err = json.Unmarshal(recorder.Body.Bytes(), &response)
		require.NoError(t, err)

		// CRITICAL: Verify llm_tools map is returned
		require.NotNil(t, response.LlmTools, "llm_tools should be present in response")
		llmTools := *response.LlmTools

		// Should have llm_tools for the "chat" function
		require.Contains(t, llmTools, "chat", "llm_tools should contain entry for 'chat' function")
		chatTools := llmTools["chat"]
		require.NotEmpty(t, chatTools, "chat should have filtered tools")

		// Verify the PDF tool is included
		assert.Len(t, chatTools, 1, "Should return 1 tool matching the filter")
		pdfTool := chatTools[0]
		assert.Equal(t, "extract_pdf", pdfTool.Name)
		assert.Equal(t, "pdf_extractor", pdfTool.Capability)
		assert.Equal(t, "Extract text from PDF files", pdfTool.Description)
		assert.NotNil(t, pdfTool.InputSchema, "InputSchema should be included")
		assert.Contains(t, pdfTool.Endpoint, "localhost:8080", "Endpoint should be built from agent info")
		assert.NotNil(t, pdfTool.Tags)
		assert.ElementsMatch(t, []string{"document", "pdf", "advanced"}, *pdfTool.Tags)

		t.Logf("✅ LLM agent received filtered tools in llm_tools response")
	})

	t.Run("ReturnEmptyLLMToolsWhenNoFilters", func(t *testing.T) {
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// Register agent without llm_filter
		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
		simpleAgent := generated.MeshAgentRegistration{
			AgentId:   "simple-agent",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "simple_func",
					Capability:   "simple",
					InputSchema: &map[string]interface{}{
						"type": "object",
					},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(8082),
		}

		jsonData, err := json.Marshal(simpleAgent)
		require.NoError(t, err)
		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		var response generated.MeshRegistrationResponse
		err = json.Unmarshal(recorder.Body.Bytes(), &response)
		require.NoError(t, err)

		// llm_tools should be nil or empty when no filters provided
		if response.LlmTools != nil {
			assert.Empty(t, *response.LlmTools, "llm_tools should be empty when no llm_filter provided")
		}

		t.Logf("✅ No llm_tools returned when agent has no llm_filter")
	})

	t.Run("MultipleLLMFiltersInOneAgent", func(t *testing.T) {
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// Register two tool providers
		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent

		// Provider 1: PDF tools
		pdfProvider := generated.MeshAgentRegistration{
			AgentId:   "pdf-service",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "extract_pdf",
					Capability:   "pdf_extractor",
					Description:  stringPtr("Extract from PDF"),
					Tags:         &[]string{"document", "pdf"},
					Version:      stringPtr("1.0.0"),
					InputSchema:  &map[string]interface{}{"type": "object"},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(9000),
		}

		jsonData, _ := json.Marshal(pdfProvider)
		req, _ := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		require.Equal(t, http.StatusOK, recorder.Code)

		// Provider 2: Web search tools
		webProvider := generated.MeshAgentRegistration{
			AgentId:   "web-service",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "search_web",
					Capability:   "web_search",
					Description:  stringPtr("Search the web"),
					Tags:         &[]string{"search", "web"},
					Version:      stringPtr("2.0.0"),
					InputSchema:  &map[string]interface{}{"type": "object"},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(9001),
		}

		jsonData, _ = json.Marshal(webProvider)
		req, _ = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		require.Equal(t, http.StatusOK, recorder.Code)

		// Register LLM agent with TWO different functions, each with different llm_filter
		llmAgent := generated.MeshAgentRegistration{
			AgentId:   "multi-llm-agent",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "document_chat",
					Capability:   "document_assistant",
					InputSchema:  &map[string]interface{}{"type": "object"},
					LlmFilter: &map[string]interface{}{
						"filter":       []interface{}{"pdf_extractor"},
						"filter_mode":  "all",
						"inject_param": "llm_tools",
					},
				},
				{
					FunctionName: "research_chat",
					Capability:   "research_assistant",
					InputSchema:  &map[string]interface{}{"type": "object"},
					LlmFilter: &map[string]interface{}{
						"filter":       []interface{}{"web_search"},
						"filter_mode":  "all",
						"inject_param": "llm_tools",
					},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(9002),
		}

		jsonData, _ = json.Marshal(llmAgent)
		req, _ = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		var response generated.MeshRegistrationResponse
		json.Unmarshal(recorder.Body.Bytes(), &response)

		// Verify llm_tools contains entries for BOTH functions
		require.NotNil(t, response.LlmTools)
		llmTools := *response.LlmTools

		require.Contains(t, llmTools, "document_chat")
		require.Contains(t, llmTools, "research_chat")

		// document_chat should only have PDF tools
		docTools := llmTools["document_chat"]
		require.Len(t, docTools, 1)
		assert.Equal(t, "extract_pdf", docTools[0].Name)

		// research_chat should only have web tools
		researchTools := llmTools["research_chat"]
		require.Len(t, researchTools, 1)
		assert.Equal(t, "search_web", researchTools[0].Name)

		t.Logf("✅ Multiple llm_filters returned separate tool sets per function")
	})

	t.Run("WildcardFilterReturnsAllTools", func(t *testing.T) {
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// Register multiple tool providers
		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent

		providers := []generated.MeshAgentRegistration{
			{
				AgentId:   "provider-1",
				AgentType: &agentType,
				Tools: []generated.MeshToolRegistration{
					{
						FunctionName: "tool1",
						Capability:   "cap1",
						InputSchema:  &map[string]interface{}{"type": "object"},
					},
				},
				HttpHost: stringPtr("localhost"),
				HttpPort: intPtr(9100),
			},
			{
				AgentId:   "provider-2",
				AgentType: &agentType,
				Tools: []generated.MeshToolRegistration{
					{
						FunctionName: "tool2",
						Capability:   "cap2",
						InputSchema:  &map[string]interface{}{"type": "object"},
					},
				},
				HttpHost: stringPtr("localhost"),
				HttpPort: intPtr(9101),
			},
		}

		for _, provider := range providers {
			jsonData, _ := json.Marshal(provider)
			req, _ := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
			req.Header.Set("Content-Type", "application/json")
			recorder := httptest.NewRecorder()
			router.ServeHTTP(recorder, req)
			require.Equal(t, http.StatusOK, recorder.Code)
		}

		// Register LLM agent with wildcard filter
		llmAgent := generated.MeshAgentRegistration{
			AgentId:   "wildcard-llm",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "universal_chat",
					Capability:   "universal_assistant",
					InputSchema:  &map[string]interface{}{"type": "object"},
					LlmFilter: &map[string]interface{}{
						"filter":       []interface{}{"*"},
						"filter_mode":  "*",
						"inject_param": "llm_tools",
					},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(9102),
		}

		jsonData, _ := json.Marshal(llmAgent)
		req, _ := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		var response generated.MeshRegistrationResponse
		json.Unmarshal(recorder.Body.Bytes(), &response)

		require.NotNil(t, response.LlmTools)
		llmTools := *response.LlmTools
		require.Contains(t, llmTools, "universal_chat")

		// Should return ALL tools (both tool1 and tool2)
		universalTools := llmTools["universal_chat"]
		assert.Len(t, universalTools, 2, "Wildcard filter should return all available tools")

		functionNames := []string{universalTools[0].Name, universalTools[1].Name}
		assert.ElementsMatch(t, []string{"tool1", "tool2"}, functionNames)

		t.Logf("✅ Wildcard filter returned all available tools")
	})

	t.Run("TopologyChangeTriggersUpdatedLLMTools", func(t *testing.T) {
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent

		// Register LLM agent first with filter
		llmAgent := generated.MeshAgentRegistration{
			AgentId:   "adaptive-llm",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "smart_chat",
					Capability:   "adaptive_chat",
					InputSchema:  &map[string]interface{}{"type": "object"},
					LlmFilter: &map[string]interface{}{
						"filter":       []interface{}{"data_processor"},
						"filter_mode":  "all",
						"inject_param": "llm_tools",
					},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(9200),
		}

		// First heartbeat - no tools available yet
		jsonData, _ := json.Marshal(llmAgent)
		req, _ := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		require.Equal(t, http.StatusOK, recorder.Code)

		var response1 generated.MeshRegistrationResponse
		json.Unmarshal(recorder.Body.Bytes(), &response1)

		// Should have empty tools since no provider exists yet
		if response1.LlmTools != nil {
			llmTools1 := *response1.LlmTools
			if tools, ok := llmTools1["smart_chat"]; ok {
				assert.Empty(t, tools, "No tools should be available yet")
			}
		}

		// Now register a tool provider
		dataProvider := generated.MeshAgentRegistration{
			AgentId:   "data-provider",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "process_data",
					Capability:   "data_processor",
					Description:  stringPtr("Process data"),
					InputSchema:  &map[string]interface{}{"type": "object"},
				},
			},
			HttpHost: stringPtr("localhost"),
			HttpPort: intPtr(9201),
		}

		jsonData, _ = json.Marshal(dataProvider)
		req, _ = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		require.Equal(t, http.StatusOK, recorder.Code)

		// Send another heartbeat for LLM agent - should now see the new tool
		jsonData, _ = json.Marshal(llmAgent)
		req, _ = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		require.Equal(t, http.StatusOK, recorder.Code)

		var response2 generated.MeshRegistrationResponse
		json.Unmarshal(recorder.Body.Bytes(), &response2)

		// Now should have the data_processor tool
		require.NotNil(t, response2.LlmTools)
		llmTools2 := *response2.LlmTools
		require.Contains(t, llmTools2, "smart_chat")
		smartTools := llmTools2["smart_chat"]
		require.Len(t, smartTools, 1, "Should now see the newly registered tool")
		assert.Equal(t, "process_data", smartTools[0].Name)

		t.Logf("✅ Topology change (new tool provider) reflected in llm_tools response")
	})
}

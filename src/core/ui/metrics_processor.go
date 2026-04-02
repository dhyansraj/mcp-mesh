package ui

import (
	"sort"
	"sync"

	"mcp-mesh/src/core/registry/tracing"
)

// MetricsProcessor aggregates dashboard-specific metrics from trace events.
// It runs as a TraceEventProcessor alongside the TraceAccumulator in the UI server,
// keeping aggregation logic out of the shared tracing package.
type MetricsProcessor struct {
	mu sync.RWMutex

	// Per-agent metrics keyed by agent name
	agentMetrics map[string]*agentMetrics

	// Per-model token usage keyed by model name
	modelMetrics map[string]*modelMetrics
}

type agentMetrics struct {
	SpanCount          int
	TotalInputTokens   int64
	TotalOutputTokens  int64
	TotalRequestBytes  int64
	TotalResponseBytes int64
}

type modelMetrics struct {
	CallCount    int
	InputTokens  int64
	OutputTokens int64
}

// AgentMetricsData is the JSON response for per-agent metrics.
type AgentMetricsData struct {
	AgentName          string `json:"agent_name"`
	SpanCount          int    `json:"span_count"`
	TotalInputTokens   int64  `json:"total_input_tokens"`
	TotalOutputTokens  int64  `json:"total_output_tokens"`
	TotalRequestBytes  int64  `json:"total_request_bytes"`
	TotalResponseBytes int64  `json:"total_response_bytes"`
}

// ModelMetricsData is the JSON response for per-model token usage.
type ModelMetricsData struct {
	Model        string `json:"model"`
	Provider     string `json:"provider"`
	CallCount    int    `json:"call_count"`
	InputTokens  int64  `json:"input_tokens"`
	OutputTokens int64  `json:"output_tokens"`
	TotalTokens  int64  `json:"total_tokens"`
}

func NewMetricsProcessor() *MetricsProcessor {
	return &MetricsProcessor{
		agentMetrics: make(map[string]*agentMetrics),
		modelMetrics: make(map[string]*modelMetrics),
	}
}

// ProcessTraceEvent implements tracing.TraceEventProcessor.
func (mp *MetricsProcessor) ProcessTraceEvent(event *tracing.TraceEvent) error {
	mp.mu.Lock()
	defer mp.mu.Unlock()

	// Per-agent metrics
	if event.AgentName != "" {
		am, exists := mp.agentMetrics[event.AgentName]
		if !exists {
			am = &agentMetrics{}
			mp.agentMetrics[event.AgentName] = am
		}
		am.SpanCount++
		if event.RequestBytes != nil {
			am.TotalRequestBytes += *event.RequestBytes
		}
		if event.ResponseBytes != nil {
			am.TotalResponseBytes += *event.ResponseBytes
		}
		if event.LlmInputTokens != nil {
			am.TotalInputTokens += *event.LlmInputTokens
		}
		if event.LlmOutputTokens != nil {
			am.TotalOutputTokens += *event.LlmOutputTokens
		}
	}

	// Per-model token tracking
	if event.LlmModel != nil && *event.LlmModel != "" {
		model := *event.LlmModel
		mm, exists := mp.modelMetrics[model]
		if !exists {
			mm = &modelMetrics{}
			mp.modelMetrics[model] = mm
		}
		mm.CallCount++
		if event.LlmInputTokens != nil {
			mm.InputTokens += *event.LlmInputTokens
		}
		if event.LlmOutputTokens != nil {
			mm.OutputTokens += *event.LlmOutputTokens
		}
	}

	return nil
}

// GetAgentMetrics returns per-agent aggregated metrics sorted by span count.
func (mp *MetricsProcessor) GetAgentMetrics() []AgentMetricsData {
	mp.mu.RLock()
	defer mp.mu.RUnlock()

	result := make([]AgentMetricsData, 0, len(mp.agentMetrics))
	for name, am := range mp.agentMetrics {
		result = append(result, AgentMetricsData{
			AgentName:          name,
			SpanCount:          am.SpanCount,
			TotalInputTokens:   am.TotalInputTokens,
			TotalOutputTokens:  am.TotalOutputTokens,
			TotalRequestBytes:  am.TotalRequestBytes,
			TotalResponseBytes: am.TotalResponseBytes,
		})
	}

	sort.Slice(result, func(i, j int) bool {
		return result[i].SpanCount > result[j].SpanCount
	})

	return result
}

// GetModelMetrics returns per-model token usage sorted by total tokens.
func (mp *MetricsProcessor) GetModelMetrics() []ModelMetricsData {
	mp.mu.RLock()
	defer mp.mu.RUnlock()

	result := make([]ModelMetricsData, 0, len(mp.modelMetrics))
	for model, mm := range mp.modelMetrics {
		provider := ""
		for i, c := range model {
			if c == '/' {
				provider = model[:i]
				break
			}
		}

		result = append(result, ModelMetricsData{
			Model:        model,
			Provider:     provider,
			CallCount:    mm.CallCount,
			InputTokens:  mm.InputTokens,
			OutputTokens: mm.OutputTokens,
			TotalTokens:  mm.InputTokens + mm.OutputTokens,
		})
	}

	sort.Slice(result, func(i, j int) bool {
		return result[i].TotalTokens > result[j].TotalTokens
	})

	return result
}

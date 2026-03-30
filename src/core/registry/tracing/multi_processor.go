package tracing

import "log"

// MultiProcessor fans out trace events to multiple processors.
// It implements TraceEventProcessor and calls each wrapped processor in order.
type MultiProcessor struct {
	processors []TraceEventProcessor
	logger     *log.Logger
}

// NewMultiProcessor creates a MultiProcessor that dispatches to all given processors.
func NewMultiProcessor(logger *log.Logger, processors ...TraceEventProcessor) *MultiProcessor {
	return &MultiProcessor{processors: processors, logger: logger}
}

// ProcessTraceEvent dispatches the event to every processor. The first error
// encountered is returned, but all processors are always called.
func (mp *MultiProcessor) ProcessTraceEvent(event *TraceEvent) error {
	var firstErr error
	for _, p := range mp.processors {
		if err := p.ProcessTraceEvent(event); err != nil {
			if firstErr == nil {
				firstErr = err
			}
			mp.logger.Printf("MultiProcessor: processor error: %v", err)
		}
	}
	return firstErr
}

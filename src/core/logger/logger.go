package logger

import (
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/config"
)

// Logger provides structured logging with level control
type Logger struct {
	config *config.Config
	out    io.Writer
	errOut io.Writer
}

// New creates a new logger instance
func New(cfg *config.Config) *Logger {
	return &Logger{
		config: cfg,
		out:    os.Stdout,
		errOut: os.Stderr,
	}
}

// formatLog formats a log message with timestamp and level to match Python format
// Format: "2026-01-05 14:24:38 INFO     message"
func (l *Logger) formatLog(level string, format string, args ...interface{}) string {
	timestamp := time.Now().Format("2006-01-02 15:04:05")
	message := fmt.Sprintf(format, args...)
	// Pad level to 8 chars to match Python's "%-8s" format
	return fmt.Sprintf("%s %-8s %s\n", timestamp, level, message)
}

// Debug logs debug messages (only if debug mode is enabled)
func (l *Logger) Debug(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("DEBUG") {
		fmt.Fprint(l.out, l.formatLog("DEBUG", format, args...))
	}
}

// Info logs info messages
func (l *Logger) Info(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("INFO") {
		fmt.Fprint(l.out, l.formatLog("INFO", format, args...))
	}
}

// Warning logs warning messages
func (l *Logger) Warning(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("WARNING") {
		fmt.Fprint(l.out, l.formatLog("WARNING", format, args...))
	}
}

// Error logs error messages
func (l *Logger) Error(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("ERROR") {
		fmt.Fprint(l.errOut, l.formatLog("ERROR", format, args...))
	}
}

// Printf provides standard log.Printf behavior for compatibility
func (l *Logger) Printf(format string, args ...interface{}) {
	l.Info(format, args...)
}

// IsDebugEnabled returns true if debug logging is enabled
func (l *Logger) IsDebugEnabled() bool {
	return l.config.ShouldLogAtLevel("DEBUG")
}

// SetGinMode sets Gin's mode based on the log level
func (l *Logger) SetGinMode() {
	if l.config.IsDebugMode() {
		// Keep gin in debug mode for verbose logging
		gin.SetMode(gin.DebugMode)
	} else {
		// Set gin to release mode to reduce noise
		gin.SetMode(gin.ReleaseMode)
	}
}

// LogLevel returns the current log level
func (l *Logger) LogLevel() string {
	return strings.ToUpper(l.config.LogLevel)
}

// GetStartupBanner returns a formatted startup banner with log level info
func (l *Logger) GetStartupBanner() string {
	debugStatus := "disabled"
	if l.config.IsDebugMode() {
		debugStatus = "enabled"
	}

	banner := fmt.Sprintf("Log Level: %s | Debug Mode: %s", l.LogLevel(), debugStatus)
	if l.config.IsTraceMode() {
		banner += " | SQL Logging: enabled"
	}
	return banner
}

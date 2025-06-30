package logger

import (
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/config"
)

// Logger provides structured logging with level control
type Logger struct {
	config     *config.Config
	debugLog   *log.Logger
	infoLog    *log.Logger
	warningLog *log.Logger
	errorLog   *log.Logger
}

// New creates a new logger instance
func New(cfg *config.Config) *Logger {
	return &Logger{
		config:     cfg,
		debugLog:   log.New(os.Stdout, "[DEBUG] ", log.LstdFlags|log.Lmicroseconds),
		infoLog:    log.New(os.Stdout, "[INFO] ", log.LstdFlags),
		warningLog: log.New(os.Stdout, "[WARNING] ", log.LstdFlags),
		errorLog:   log.New(os.Stderr, "[ERROR] ", log.LstdFlags),
	}
}

// Debug logs debug messages (only if debug mode is enabled)
func (l *Logger) Debug(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("DEBUG") {
		l.debugLog.Printf(format, args...)
	}
}

// Info logs info messages
func (l *Logger) Info(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("INFO") {
		l.infoLog.Printf(format, args...)
	}
}

// Warning logs warning messages
func (l *Logger) Warning(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("WARNING") {
		l.warningLog.Printf(format, args...)
	}
}

// Error logs error messages
func (l *Logger) Error(format string, args ...interface{}) {
	if l.config.ShouldLogAtLevel("ERROR") {
		l.errorLog.Printf(format, args...)
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

	return fmt.Sprintf("Log Level: %s | Debug Mode: %s", l.LogLevel(), debugStatus)
}

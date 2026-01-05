package cli

import (
	"fmt"
	"io"
	"os"
	"time"
)

// CLILogger provides consistent log formatting matching Python agent format
// Format: "2026-01-05 14:24:38 INFO     message"
type CLILogger struct {
	prefix string
	out    io.Writer
}

// NewCLILogger creates a new CLI logger with the given prefix
func NewCLILogger(prefix string) *CLILogger {
	return &CLILogger{
		prefix: prefix,
		out:    os.Stdout,
	}
}

// Printf formats and prints a log message matching Python format
func (l *CLILogger) Printf(format string, args ...interface{}) {
	timestamp := time.Now().Format("2006-01-02 15:04:05")
	message := fmt.Sprintf(format, args...)
	fmt.Fprintf(l.out, "%s %-8s %s\n", timestamp, l.prefix, message)
}

// Println prints a log message matching Python format
func (l *CLILogger) Println(args ...interface{}) {
	timestamp := time.Now().Format("2006-01-02 15:04:05")
	message := fmt.Sprint(args...)
	fmt.Fprintf(l.out, "%s %-8s %s\n", timestamp, l.prefix, message)
}

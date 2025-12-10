package main

import "embed"

// EmbeddedTemplates contains all scaffold templates embedded in the binary.
// This allows meshctl to work without external template files.
// The "all:" prefix includes hidden files (starting with .) like .dockerignore
//
//go:embed all:templates
var EmbeddedTemplates embed.FS

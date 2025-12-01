package main

import "embed"

// EmbeddedTemplates contains all scaffold templates embedded in the binary.
// This allows meshctl to work without external template files.
//
//go:embed templates
var EmbeddedTemplates embed.FS

package main

import "embed"

// EmbeddedSPA contains the Next.js static export for the dashboard.
// Built via: cd src/ui && npm run build
// The output directory "out" contains the static HTML/JS/CSS files.
//
//go:embed all:out
var EmbeddedSPA embed.FS

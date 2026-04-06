package main

import "embed"

// EmbeddedSPA contains the Vite static build for the dashboard.
// Built via: cd src/ui && npm run build
// The output directory "dist" contains the static HTML/JS/CSS files.
//
//go:embed all:dist
var EmbeddedSPA embed.FS

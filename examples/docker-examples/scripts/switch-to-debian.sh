#!/bin/bash

# Switch to Debian-based registry build for better SQLite compatibility
# This is useful if the Alpine build fails due to musl/SQLite issues

set -e

echo "🔄 Switching to Debian-based registry build..."

# Backup original docker-compose.yml
if [ ! -f "docker-compose.yml.backup" ]; then
    cp docker-compose.yml docker-compose.yml.backup
    echo "✅ Backed up original docker-compose.yml"
fi

# Update docker-compose.yml to use Debian Dockerfile
sed -i.tmp 's|dockerfile: examples/docker-examples/registry/Dockerfile|dockerfile: examples/docker-examples/registry/Dockerfile.debian|g' docker-compose.yml

# Clean up temp file
rm -f docker-compose.yml.tmp

echo "✅ Updated docker-compose.yml to use Dockerfile.debian"
echo "📝 Original file backed up as docker-compose.yml.backup"
echo ""
echo "Now run: docker-compose build registry"

#!/usr/bin/env bash
# teardown.sh — Remove TripPlanner from Kubernetes
set -euo pipefail

NAMESPACE="trip-planner"

echo "=== Uninstalling agents ==="
AGENTS=(
  flight-agent hotel-agent weather-agent poi-agent user-prefs-agent
  chat-history-agent claude-provider openai-provider planner-agent
  gateway budget-analyst adventure-advisor logistics-planner
)

for agent in "${AGENTS[@]}"; do
  helm uninstall "$agent" -n "$NAMESPACE" 2>/dev/null && \
    echo "  Removed $agent" || echo "  $agent not found (skipped)"
done

echo ""
echo "=== Uninstalling core ==="
helm uninstall mcp-core -n "$NAMESPACE" 2>/dev/null && \
  echo "  Removed mcp-core" || echo "  mcp-core not found (skipped)"

echo ""
echo "=== Deleting namespace ==="
kubectl delete namespace "$NAMESPACE" --ignore-not-found

echo ""
echo "=== Done ==="

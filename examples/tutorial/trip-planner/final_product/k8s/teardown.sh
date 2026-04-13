#!/usr/bin/env bash
# teardown.sh — Remove TripPlanner from Kubernetes
set -euo pipefail

NAMESPACE="${1:-trip-planner}"

echo "=== Removing nginx ==="
kubectl delete -f "$(dirname "$0")/nginx/" -n "$NAMESPACE" --ignore-not-found

echo ""
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
echo "=== Removing SPIRE ==="
kubectl delete job spire-registration -n "$NAMESPACE" --ignore-not-found
kubectl delete -f "$(dirname "$0")/spire/spire-agent.yaml" -n "$NAMESPACE" --ignore-not-found
kubectl delete -f "$(dirname "$0")/spire/spire-server.yaml" -n "$NAMESPACE" --ignore-not-found

echo ""
echo "=== Removing secrets ==="
kubectl delete secret llm-keys -n "$NAMESPACE" --ignore-not-found
kubectl delete secret nginx-oauth -n "$NAMESPACE" --ignore-not-found

echo ""
echo "=== Removing SPIRE ClusterRole/ClusterRoleBinding ==="
kubectl delete clusterrolebinding spire-server-trust-binding --ignore-not-found
kubectl delete clusterrole spire-server-trust-role --ignore-not-found
kubectl delete clusterrolebinding spire-agent-binding --ignore-not-found
kubectl delete clusterrole spire-agent-role --ignore-not-found

echo ""
echo "=== Deleting namespace ==="
kubectl delete namespace "$NAMESPACE" --ignore-not-found

echo ""
echo "=== Done ==="

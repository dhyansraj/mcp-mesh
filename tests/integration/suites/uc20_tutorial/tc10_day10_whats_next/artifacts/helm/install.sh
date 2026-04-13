#!/usr/bin/env bash
# --8<-- [start:full_file]
# install.sh — Deploy TripPlanner to Kubernetes with Helm
#
# Prerequisites:
#   - kubectl configured (minikube, EKS, GKE, etc.)
#   - Helm 3.8+ (OCI registry support)
#   - ANTHROPIC_API_KEY and OPENAI_API_KEY set in environment
#
# Usage:
#   ./install.sh           # Full deploy
#   ./install.sh --dry-run # Preview only

set -euo pipefail

NAMESPACE="trip-planner"
CHART_VERSION="1.2.0"
AGENT_CHART="oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent"
CORE_CHART="oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=""

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN="--dry-run"
  echo "=== DRY RUN — no changes will be made ==="
fi

echo "=== Step 1: Create namespace ==="
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "=== Step 2: Create secrets ==="
if [[ -z "${ANTHROPIC_API_KEY:-}" ]] || [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "WARNING: ANTHROPIC_API_KEY or OPENAI_API_KEY not set."
  echo "LLM agents will start but cannot call provider APIs."
  echo "Set them and re-run, or create the secret manually:"
  echo "  kubectl -n $NAMESPACE create secret generic llm-keys \\"
  echo "    --from-literal=ANTHROPIC_API_KEY=sk-ant-... \\"
  echo "    --from-literal=OPENAI_API_KEY=sk-..."
fi

kubectl -n "$NAMESPACE" create secret generic llm-keys \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-placeholder}" \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY:-placeholder}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "=== Step 3: Install core infrastructure ==="
helm upgrade --install mcp-core "$CORE_CHART" \
  --version "$CHART_VERSION" \
  -n "$NAMESPACE" \
  -f "$SCRIPT_DIR/values-core.yaml" \
  --wait --timeout 3m \
  $DRY_RUN

echo ""
echo "=== Step 4: Wait for registry ==="
if [[ -z "$DRY_RUN" ]]; then
  kubectl wait --for=condition=available deployment/mcp-core-mcp-mesh-registry \
    -n "$NAMESPACE" --timeout=120s
fi

echo ""
echo "=== Step 5: Install agents ==="
# --8<-- [start:agent_loop]
AGENTS=(
  flight-agent
  hotel-agent
  weather-agent
  poi-agent
  user-prefs-agent
  chat-history-agent
  claude-provider
  openai-provider
  planner-agent
  gateway
  budget-analyst
  adventure-advisor
  logistics-planner
)

for agent in "${AGENTS[@]}"; do
  echo "  Installing $agent..."
  helm upgrade --install "$agent" "$AGENT_CHART" \
    --version "$CHART_VERSION" \
    -n "$NAMESPACE" \
    -f "$SCRIPT_DIR/values-${agent}.yaml" \
    $DRY_RUN
done
# --8<-- [end:agent_loop]

echo ""
echo "=== Step 6: Wait for agents ==="
if [[ -z "$DRY_RUN" ]]; then
  echo "Waiting for all deployments to become available..."
  for agent in "${AGENTS[@]}"; do
    kubectl wait --for=condition=available "deployment/${agent}-mcp-mesh-agent" \
      -n "$NAMESPACE" --timeout=120s 2>/dev/null || \
      echo "  $agent not ready yet (may still be pulling image)"
  done
fi

echo ""
echo "=== Done ==="
echo ""
echo "Verify:"
echo "  kubectl -n $NAMESPACE get pods"
echo "  kubectl -n $NAMESPACE port-forward svc/mcp-core-mcp-mesh-registry 8000:8000 &"
echo "  meshctl list"
echo ""
echo "Test the gateway:"
echo "  kubectl -n $NAMESPACE port-forward svc/gateway-mcp-mesh-agent 8080:8080 &"
echo "  curl -s -X POST http://localhost:8080/plan \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"destination\":\"Kyoto\",\"dates\":\"June 1-5\",\"budget\":\"\$2000\"}'"
# --8<-- [end:full_file]

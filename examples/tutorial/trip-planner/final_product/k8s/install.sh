#!/usr/bin/env bash
# install.sh — Deploy TripPlanner to Kubernetes with SPIRE security
#
# Prerequisites:
#   - kubectl configured (minikube, EKS, GKE, etc.)
#   - Helm 3.8+ (OCI registry support)
#   - ANTHROPIC_API_KEY and OPENAI_API_KEY set in environment
#   - Agent Docker images built and pushed to your registry
#
# Usage:
#   ./install.sh                    # Full deploy to trip-planner namespace
#   ./install.sh staging            # Deploy to custom namespace
#   ./install.sh trip-planner --dry-run  # Preview only

set -euo pipefail

NAMESPACE="${1:-trip-planner}"
DRY_RUN=""
CHART_VERSION="1.2.0"
AGENT_CHART="oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent"
CORE_CHART="oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check for --dry-run in any position
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN="--dry-run"
    echo "=== DRY RUN -- no changes will be made ==="
  fi
done

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
echo "=== Step 3: Deploy SPIRE infrastructure ==="
kubectl apply -f "$SCRIPT_DIR/spire/spire-server.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/spire/spire-agent.yaml" -n "$NAMESPACE"

echo ""
echo "=== Step 4: Wait for SPIRE server ==="
if [[ -z "$DRY_RUN" ]]; then
  echo "Waiting for SPIRE server to be ready..."
  kubectl wait --for=condition=ready pod -l app=spire-server \
    -n "$NAMESPACE" --timeout=90s
fi

echo ""
echo "=== Step 5: Register SPIRE workload entries ==="
# Delete previous registration job if it exists
kubectl delete job spire-registration -n "$NAMESPACE" --ignore-not-found
kubectl apply -f "$SCRIPT_DIR/spire/registration-entries.yaml" -n "$NAMESPACE"
if [[ -z "$DRY_RUN" ]]; then
  echo "Waiting for registration to complete..."
  kubectl wait --for=condition=complete job/spire-registration \
    -n "$NAMESPACE" --timeout=60s
fi

echo ""
echo "=== Step 6: Install core infrastructure ==="
helm upgrade --install mcp-core "$CORE_CHART" \
  --version "$CHART_VERSION" \
  -n "$NAMESPACE" \
  -f "$SCRIPT_DIR/helm/values-core.yaml" \
  --wait --timeout 3m \
  $DRY_RUN

echo ""
echo "=== Step 7: Wait for registry ==="
if [[ -z "$DRY_RUN" ]]; then
  kubectl wait --for=condition=available deployment/mcp-core-mcp-mesh-registry \
    -n "$NAMESPACE" --timeout=120s
fi

echo ""
echo "=== Step 8: Install agents ==="
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
    -f "$SCRIPT_DIR/helm/values-${agent}.yaml" \
    $DRY_RUN
done

echo ""
echo "=== Step 9: Wait for agents ==="
if [[ -z "$DRY_RUN" ]]; then
  echo "Waiting for all deployments to become available..."
  for agent in "${AGENTS[@]}"; do
    kubectl wait --for=condition=available "deployment/${agent}-mcp-mesh-agent" \
      -n "$NAMESPACE" --timeout=120s 2>/dev/null || \
      echo "  $agent not ready yet (may still be pulling image)"
  done
fi

echo ""
echo "=== Step 10: Deploy nginx ==="
kubectl apply -f "$SCRIPT_DIR/nginx/secret.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/nginx/configmap.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/nginx/deployment.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/nginx/service.yaml" -n "$NAMESPACE"

if [[ -z "$DRY_RUN" ]]; then
  kubectl wait --for=condition=available deployment/nginx \
    -n "$NAMESPACE" --timeout=60s 2>/dev/null || \
    echo "  nginx not ready yet (may still be pulling image)"
fi

echo ""
echo "=== Done ==="
echo ""
echo "Verify:"
echo "  kubectl -n $NAMESPACE get pods"
echo "  kubectl -n $NAMESPACE port-forward svc/mcp-core-mcp-mesh-registry 8000:8000 &"
echo "  meshctl list"
echo ""
echo "Access the UI:"
echo "  kubectl -n $NAMESPACE port-forward svc/nginx 80:80"
echo "  open http://localhost"
echo ""
echo "Test the gateway directly:"
echo "  kubectl -n $NAMESPACE port-forward svc/gateway-mcp-mesh-agent 8080:8080 &"
echo "  curl -s -X POST http://localhost:8080/plan \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"destination\":\"Kyoto\",\"dates\":\"June 1-5\",\"budget\":\"\$2000\"}'"

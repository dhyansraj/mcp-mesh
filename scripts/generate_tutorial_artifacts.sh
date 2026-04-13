#!/usr/bin/env bash
set -euo pipefail

# Generate downloadable tutorial artifacts:
#   - Per-day zip files for days 01-10
#   - Final product zip
#   - Concatenated tutorial-complete.txt

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TUTORIAL_DIR="$REPO_ROOT/examples/tutorial/trip-planner"
DOCS_DIR="$REPO_ROOT/docs"
DOWNLOAD_DIR="$DOCS_DIR/downloads"
TUTORIAL_DOCS="$DOCS_DIR/tutorial"

# Common exclusion patterns for zip
EXCLUDE_PATTERNS=(
    "*__pycache__*"
    "*.pyc"
    "*node_modules*"
    "*/dist/*"
    "*/.venv/*"
    "*.db"
    "*.db-shm"
    "*.db-wal"
    "*.DS_Store"
)

build_exclude_args() {
    local args=()
    for pattern in "${EXCLUDE_PATTERNS[@]}"; do
        args+=(-x "$pattern")
    done
    echo "${args[@]}"
}

echo "=== Generating tutorial artifacts ==="
echo ""

mkdir -p "$DOWNLOAD_DIR"

# Day name mapping
declare -A DAY_NAMES
DAY_NAMES[01]="scaffold"
DAY_NAMES[02]="dependency-injection"
DAY_NAMES[03]="llm-provider"
DAY_NAMES[04]="provider-tiers"
DAY_NAMES[05]="http-gateway"
DAY_NAMES[06]="chat-history"
DAY_NAMES[07]="committee"
DAY_NAMES[08]="docker-compose"
DAY_NAMES[09]="kubernetes"
DAY_NAMES[10]="whats-next"

# Generate per-day zips
for day_num in 01 02 03 04 05 06 07 08 09 10; do
    day_dir="$TUTORIAL_DIR/day-$day_num"
    zip_name="day-${day_num}-${DAY_NAMES[$day_num]}.zip"
    zip_path="$DOWNLOAD_DIR/$zip_name"

    if [ ! -d "$day_dir" ]; then
        echo "[SKIP] day-$day_num directory not found"
        continue
    fi

    echo "[ZIP]  day-$day_num -> $zip_name"
    (cd "$day_dir" && zip -r -q "$zip_path" . $(build_exclude_args))
done

# Generate final product zip
echo "[ZIP]  final_product -> final-product.zip"
(cd "$TUTORIAL_DIR/final_product" && zip -r -q "$DOWNLOAD_DIR/final-product.zip" . $(build_exclude_args))

# Generate concatenated tutorial markdown
echo "[MD]   Generating tutorial-complete.txt"

COMPLETE_MD="$DOWNLOAD_DIR/tutorial-complete.txt"

cat > "$COMPLETE_MD" << 'TITLEPAGE'
---
title: "The TripPlanner Tutorial — Complete"
subtitle: "Build a production-grade multi-agent system with MCP Mesh"
---

TITLEPAGE

# List of files in order
TUTORIAL_FILES=(
    "$TUTORIAL_DOCS/index.md"
    "$TUTORIAL_DOCS/prerequisites.md"
    "$TUTORIAL_DOCS/day-01-scaffold.md"
    "$TUTORIAL_DOCS/day-02-dependency-injection.md"
    "$TUTORIAL_DOCS/day-03-llm-provider.md"
    "$TUTORIAL_DOCS/day-04-provider-tiers.md"
    "$TUTORIAL_DOCS/day-05-http-gateway.md"
    "$TUTORIAL_DOCS/day-06-chat-history.md"
    "$TUTORIAL_DOCS/day-07-committee.md"
    "$TUTORIAL_DOCS/day-08-docker-compose.md"
    "$TUTORIAL_DOCS/day-09-kubernetes.md"
    "$TUTORIAL_DOCS/day-10-whats-next.md"
)

for file in "${TUTORIAL_FILES[@]}"; do
    file=$(eval echo "$file")  # Expand variables
    if [ ! -f "$file" ]; then
        echo "  [WARN] Missing: $file"
        continue
    fi

    # Add page break between chapters
    echo "" >> "$COMPLETE_MD"
    echo "---" >> "$COMPLETE_MD"
    echo "" >> "$COMPLETE_MD"

    # Process the file: replace snippet includes with a note
    sed 's/--8<-- ".*"/> *See the source code in the day'\''s example directory.*/' "$file" >> "$COMPLETE_MD"
done

# Generate standalone HTML (works everywhere, print-to-PDF from browser)
if command -v pandoc &> /dev/null; then
    echo "[HTML] Generating tutorial-complete.html"
    pandoc "$COMPLETE_MD" \
        -f markdown \
        -o "$DOWNLOAD_DIR/tutorial-complete.html" \
        --standalone \
        --toc \
        --toc-depth=2 \
        --metadata title="The TripPlanner Tutorial" \
        --css="https://cdn.jsdelivr.net/npm/water.css@2/out/water.min.css" \
        2>/dev/null && echo "       Open in browser and print to PDF (Cmd+P)" || {
        echo "  [WARN] HTML generation failed"
    }
else
    echo "[SKIP] pandoc not found — skipping HTML generation"
    echo "       Install with: brew install pandoc"
fi

echo ""
echo "=== Generated artifacts ==="
echo ""

total_size=0
for f in "$DOWNLOAD_DIR"/*; do
    size=$(wc -c < "$f" | tr -d ' ')
    human_size=$(ls -lh "$f" | awk '{print $5}')
    printf "  %-45s %s\n" "$(basename "$f")" "$human_size"
    total_size=$((total_size + size))
done

# Human-readable total
if [ "$total_size" -gt 1048576 ]; then
    total_human="$(echo "scale=1; $total_size / 1048576" | bc)M"
elif [ "$total_size" -gt 1024 ]; then
    total_human="$(echo "scale=1; $total_size / 1024" | bc)K"
else
    total_human="${total_size}B"
fi

echo ""
echo "Total: $total_human"
echo "Location: $DOWNLOAD_DIR"

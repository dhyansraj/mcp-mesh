#!/usr/bin/env python3
"""
View and analyze traces from Redis stream.

Usage:
    python view_traces.py           # View all traces
    python view_traces.py --tree    # View as hierarchy tree
    python view_traces.py --clear   # Clear all traces
"""

import argparse
import json
import sys
from collections import defaultdict

import redis


def get_traces(r: redis.Redis) -> list[dict]:
    """Fetch all traces from Redis stream."""
    result = r.xread({"mesh:trace": "0"})
    if not result:
        return []

    traces = []
    for stream, messages in result:
        for msg_id, data in messages:
            trace = {
                "_msg_id": msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            }
            for key, value in data.items():
                key = key.decode() if isinstance(key, bytes) else key
                value = value.decode() if isinstance(value, bytes) else value
                # Try to parse JSON values
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
                trace[key] = value
            traces.append(trace)

    return traces


def print_traces_table(traces: list[dict]):
    """Print traces as a table."""
    if not traces:
        print("No traces found.")
        return

    print(f"\n{'='*100}")
    print(
        f"{'#':<3} {'function_name':<25} {'agent':<15} {'span_id':<12} {'parent_span':<12} {'duration_ms':<10}"
    )
    print(f"{'='*100}")

    for i, trace in enumerate(traces, 1):
        func = trace.get("function_name", "?")[:24]
        agent = trace.get("agent_name", "?")[:14]
        span = trace.get("span_id", "?")[:11]
        parent = trace.get("parent_span", "?")
        if parent:
            parent = parent[:11]
        else:
            parent = "(root)"
        duration = trace.get("duration_ms", "?")

        print(f"{i:<3} {func:<25} {agent:<15} {span:<12} {parent:<12} {duration:<10}")

    print(f"{'='*100}")
    print(f"Total traces: {len(traces)}")


def build_tree(traces: list[dict]) -> dict:
    """Build a tree structure from traces."""
    by_span = {t.get("span_id"): t for t in traces if t.get("span_id")}
    children = defaultdict(list)

    roots = []
    for trace in traces:
        parent = trace.get("parent_span")
        if not parent or parent not in by_span:
            roots.append(trace)
        else:
            children[parent].append(trace)

    return {"roots": roots, "children": children}


def print_tree_node(
    trace: dict, children: dict, prefix: str = "", is_last: bool = True
):
    """Print a single node in the tree."""
    connector = "└── " if is_last else "├── "
    func = trace.get("function_name", "?")
    agent = trace.get("agent_name", "?")
    span = trace.get("span_id", "?")[:8]
    duration = trace.get("duration_ms", "?")

    print(f"{prefix}{connector}{span}: {func} ({agent}) [{duration}ms]")

    span_id = trace.get("span_id")
    child_traces = children.get(span_id, [])
    child_count = len(child_traces)

    for i, child in enumerate(child_traces):
        is_last_child = i == child_count - 1
        new_prefix = prefix + ("    " if is_last else "│   ")
        print_tree_node(child, children, new_prefix, is_last_child)


def print_traces_tree(traces: list[dict]):
    """Print traces as a hierarchy tree."""
    if not traces:
        print("No traces found.")
        return

    tree = build_tree(traces)
    roots = tree["roots"]
    children = tree["children"]

    # Find unique trace_ids
    trace_ids = set(t.get("trace_id") for t in traces if t.get("trace_id"))

    print(f"\n{'='*80}")
    print(f"Trace Hierarchy ({len(traces)} spans, {len(trace_ids)} trace(s))")
    print(f"{'='*80}\n")

    for i, root in enumerate(roots):
        trace_id = root.get("trace_id", "?")[:8]
        print(f"Trace: {trace_id}...")
        print_tree_node(root, children, "", i == len(roots) - 1)
        print()

    # Check for orphans (spans with parent_span that doesn't exist)
    all_spans = {t.get("span_id") for t in traces}
    orphans = [
        t
        for t in traces
        if t.get("parent_span")
        and t.get("parent_span") not in all_spans
        and t not in roots
    ]

    if orphans:
        print(f"\n⚠️  WARNING: {len(orphans)} orphan spans (parent not in trace):")
        for orphan in orphans:
            func = orphan.get("function_name", "?")
            agent = orphan.get("agent_name", "?")
            parent = orphan.get("parent_span", "?")[:8]
            print(f"   - {func} ({agent}) → parent: {parent}...")


def analyze_hierarchy(traces: list[dict]):
    """Analyze trace hierarchy for issues."""
    print(f"\n{'='*80}")
    print("Hierarchy Analysis")
    print(f"{'='*80}\n")

    # Group by agent
    by_agent = defaultdict(list)
    for t in traces:
        by_agent[t.get("agent_name", "unknown")].append(t)

    print("Spans per agent:")
    for agent, spans in sorted(by_agent.items()):
        print(f"  {agent}: {len(spans)} spans")

    # Check for flat hierarchy (bug indicator)
    parent_spans = set(t.get("parent_span") for t in traces if t.get("parent_span"))
    if len(parent_spans) == 1:
        print("\n⚠️  BUG DETECTED: All spans have the same parent!")
        print("   This indicates the trace context is not being propagated correctly.")
        common_parent = list(parent_spans)[0]
        print(f"   Common parent: {str(common_parent)[:16]}...")

    # Check depth
    tree = build_tree(traces)

    def get_depth(span_id, children, depth=0):
        max_depth = depth
        for child in children.get(span_id, []):
            child_depth = get_depth(child.get("span_id"), children, depth + 1)
            max_depth = max(max_depth, child_depth)
        return max_depth

    max_depth = 0
    for root in tree["roots"]:
        depth = get_depth(root.get("span_id"), tree["children"], 1)
        max_depth = max(max_depth, depth)

    print(f"\nMax trace depth: {max_depth}")
    if max_depth <= 2 and len(traces) > 3:
        print("⚠️  Trace depth is suspiciously shallow for the number of spans.")


def main():
    parser = argparse.ArgumentParser(description="View MCP Mesh traces from Redis")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument("--tree", action="store_true", help="Show as hierarchy tree")
    parser.add_argument(
        "--analyze", action="store_true", help="Analyze trace hierarchy"
    )
    parser.add_argument("--clear", action="store_true", help="Clear all traces")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    try:
        r = redis.Redis(host=args.host, port=args.port)
        r.ping()
    except redis.ConnectionError:
        print(f"Error: Cannot connect to Redis at {args.host}:{args.port}")
        sys.exit(1)

    if args.clear:
        count = r.delete("mesh:trace")
        print(f"Cleared {count} trace stream(s)")
        return

    traces = get_traces(r)

    if args.json:
        print(json.dumps(traces, indent=2, default=str))
    elif args.tree:
        print_traces_tree(traces)
        if args.analyze:
            analyze_hierarchy(traces)
    elif args.analyze:
        print_traces_table(traces)
        analyze_hierarchy(traces)
    else:
        print_traces_table(traces)


if __name__ == "__main__":
    main()

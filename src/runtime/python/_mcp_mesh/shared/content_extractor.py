"""Content extraction for all MCP response types."""

import json
import logging
from typing import Any, Union

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Handles all MCP content types and response formats."""

    @staticmethod
    def extract_content(mcp_result: Any) -> Any:
        """Extract content from MCP result based on type.

        Supports:
        - TextContent: {"type": "text", "text": "..."}
        - ImageContent: {"type": "image", "data": "...", "mimeType": "..."}
        - ResourceContent: {"type": "resource", "resource": {...}, "text": "..."}
        - Mixed content arrays
        """
        if hasattr(mcp_result, "isError") and mcp_result.isError:
            raise RuntimeError(f"MCP Error: {mcp_result.error}")

        # Handle result content
        if hasattr(mcp_result, "content"):
            content = mcp_result.content
        elif isinstance(mcp_result, dict) and "content" in mcp_result:
            content = mcp_result["content"]
        else:
            # Fallback for non-standard response
            return str(mcp_result)

        if not content:
            return ""

        # Single content item - extract based on type
        if len(content) == 1:
            return ContentExtractor._extract_single_content(content[0])

        # Multiple content items - return structured format
        return ContentExtractor._extract_multi_content(content)

    @staticmethod
    def _extract_single_content(content_item: Any) -> Any:
        """Extract single content item."""
        if isinstance(content_item, dict):
            content_type = content_item.get("type", "unknown")

            if content_type == "text":
                text = content_item.get("text", "")
                # Try to parse as JSON for backward compatibility
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text

            elif content_type == "image":
                return {
                    "type": "image",
                    "data": content_item.get("data", ""),
                    "mimeType": content_item.get("mimeType", "image/png"),
                }

            elif content_type == "resource":
                return {
                    "type": "resource",
                    "resource": content_item.get("resource", {}),
                    "text": content_item.get("text", ""),
                }

            elif "object" in content_item:
                # FastMCP object format
                return content_item["object"]

        # Fallback to string representation
        return str(content_item)

    @staticmethod
    def _extract_multi_content(content_items: list[Any]) -> dict[str, Any]:
        """Extract multiple content items into structured format."""
        result = {"type": "multi_content", "items": [], "text_summary": ""}

        text_parts = []

        for item in content_items:
            extracted = ContentExtractor._extract_single_content(item)
            result["items"].append(extracted)

            # Build text summary
            if isinstance(extracted, dict):
                if extracted.get("type") == "text":
                    text_parts.append(str(extracted))
                elif extracted.get("type") == "resource":
                    text_parts.append(extracted.get("text", ""))
                else:
                    text_parts.append(f"[{extracted.get('type', 'content')}]")
            else:
                text_parts.append(str(extracted))

        result["text_summary"] = " ".join(text_parts)
        return result

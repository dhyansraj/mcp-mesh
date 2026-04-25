"""Resolve resource_link URIs to provider-native multimodal content."""

import base64
import json
import logging
from typing import Any

from .media_store import get_media_store

logger = logging.getLogger(__name__)

# MIME types we can inline as images
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

# MIME types for PDF documents
PDF_MIME_TYPES = {"application/pdf"}

# MIME types for text-based files (read content as text)
TEXT_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/html",
    "text/xml",
    "application/json",
    "application/xml",
    "application/csv",
}


def _format_for_claude(b64_data: str, mime_type: str) -> dict:
    """Format base64 image data for Claude/Anthropic API."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": b64_data,
        },
    }


def _format_for_openai(b64_data: str, mime_type: str) -> dict:
    """Format base64 image data for OpenAI API."""
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime_type};base64,{b64_data}",
            "detail": "high",
        },
    }


def _format_for_gemini(b64_data: str, mime_type: str) -> dict:
    """Format base64 image data for Gemini (via LiteLLM OpenAI-compatible format)."""
    return _format_for_openai(b64_data, mime_type)


_VENDOR_FORMATTERS = {
    "anthropic": _format_for_claude,
    "openai": _format_for_openai,
    "gemini": _format_for_gemini,
    "google": _format_for_gemini,
    "vertex_ai": _format_for_gemini,
}


def _format_pdf_for_claude(b64_data: str) -> dict:
    """Format PDF for Claude/Anthropic API (native document support)."""
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": b64_data,
        },
    }


def _format_pdf_for_openai(b64_data: str, filename: str) -> dict:
    """OpenAI doesn't support PDF natively — return text description."""
    return {
        "type": "text",
        "text": (
            f"[Attached PDF document: {filename}. "
            "OpenAI does not support PDF analysis. "
            "Please use Claude for PDF processing.]"
        ),
    }


def _format_pdf_for_gemini(b64_data: str, filename: str) -> dict:
    """Gemini PDF support via LiteLLM may vary — return text description."""
    return {
        "type": "text",
        "text": f"[Attached PDF document: {filename}. Gemini PDF support via LiteLLM may vary.]",
    }


def _format_text_content(data: bytes, mime_type: str, filename: str) -> dict:
    """Format text file content as a text block.

    Reads the raw bytes as UTF-8 (falling back to latin-1) and returns
    a text content dict suitable for any LLM provider.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")

    max_chars = 50_000
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... truncated, {len(text)} total characters]"

    return {
        "type": "text",
        "text": f"--- Content of {filename} ({mime_type}) ---\n{text}\n--- End of {filename} ---",
    }


async def _resolve_single_resource_link(resource_link: dict, vendor: str) -> dict:
    """Resolve a single resource_link dict to a provider-native content part.

    Args:
        resource_link: Dict with type "resource_link" and a "resource" sub-dict.
        vendor: One of "anthropic", "openai", "gemini".

    Returns:
        Provider-native content dict (image block, document block, text block,
        or text fallback).
    """
    resource = resource_link.get("resource", {})
    uri = resource.get("uri", "")
    mime_type = resource.get("mimeType", "")
    name = resource.get("name", uri)

    store = get_media_store()

    # --- Images: existing behaviour ---
    if mime_type in IMAGE_MIME_TYPES:
        try:
            data, fetched_mime = await store.fetch(uri)
            b64_data = base64.b64encode(data).decode("ascii")

            formatter = _VENDOR_FORMATTERS.get(vendor, _format_for_openai)
            result = formatter(b64_data, mime_type or fetched_mime)
            logger.debug(
                "Resolved resource_link %s to %s image block (%d bytes)",
                name,
                vendor,
                len(data),
            )
            return result
        except Exception as exc:
            logger.warning("Failed to fetch resource_link %s: %s", uri, exc)
            return {
                "type": "text",
                "text": f"[resource_link: {name} ({mime_type or 'unknown'}) at {uri} (fetch failed)]",
            }

    # --- PDFs: provider-specific ---
    if mime_type in PDF_MIME_TYPES:
        try:
            data, _fetched_mime = await store.fetch(uri)
            b64_data = base64.b64encode(data).decode("ascii")
            if vendor in ("anthropic", "claude"):
                return _format_pdf_for_claude(b64_data)
            elif vendor in ("gemini", "google", "vertex_ai"):
                return _format_pdf_for_gemini(b64_data, name)
            else:
                return _format_pdf_for_openai(b64_data, name)
        except Exception as exc:
            logger.warning("Failed to fetch PDF %s: %s", uri, exc)
            return {"type": "text", "text": f"[PDF document: {name} at {uri}]"}

    # --- Text files: read content and include as text (all providers) ---
    if mime_type in TEXT_MIME_TYPES or mime_type.startswith("text/"):
        try:
            data, _fetched_mime = await store.fetch(uri)
            return _format_text_content(data, mime_type, name)
        except Exception as exc:
            logger.warning("Failed to fetch text file %s: %s", uri, exc)
            return {"type": "text", "text": f"[Text document: {name} at {uri}]"}

    # --- Unknown / unsupported MIME type ---
    return {
        "type": "text",
        "text": f"[resource_link: {name} ({mime_type or 'unknown'}) at {uri}]",
    }


async def resolve_resource_links(tool_result: Any, vendor: str) -> list[dict]:
    """Scan tool result for resource_link items and resolve to provider-native format.

    Returns a list of content parts for the LLM message.
    - For image resource_links: fetches bytes, base64 encodes, formats per vendor
    - For non-image or non-resource_link: wraps in text content

    Args:
        tool_result: The raw tool result (could be dict, list, string, etc.)
        vendor: One of "anthropic", "openai", "gemini" (determines output format)

    Returns:
        List of content dicts suitable for provider-specific message content arrays.
    """
    # resource_link dict
    if isinstance(tool_result, dict) and tool_result.get("type") == "resource_link":
        part = await _resolve_single_resource_link(tool_result, vendor)
        return [part]

    # multi_content dict (from ContentExtractor._extract_multi_content or proxy)
    if isinstance(tool_result, dict) and tool_result.get("type") == "multi_content":
        items = tool_result.get("items") or tool_result.get("content") or []
        parts: list[dict] = []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "resource_link":
                parts.append(await _resolve_single_resource_link(item, vendor))
            elif isinstance(item, str):
                parts.append({"type": "text", "text": item})
            elif isinstance(item, dict):
                parts.append({"type": "text", "text": json.dumps(item)})
            else:
                parts.append({"type": "text", "text": str(item)})
        return parts

    # Plain string
    if isinstance(tool_result, str):
        return [{"type": "text", "text": tool_result}]

    # Anything else (dict without resource_link type, list, number, etc.)
    try:
        text = json.dumps(tool_result)
    except (TypeError, ValueError):
        text = str(tool_result)
    return [{"type": "text", "text": text}]


# Vendors that do NOT support images in tool/function result messages.
# These require images to be sent in a separate user message.
# Anthropic/Claude supports images inline in tool messages, so it is not listed here.
# For OpenAI and Gemini, images are sent in a follow-up user message using
# OpenAI-compatible format (image_url with data URI), which LiteLLM converts
# to the provider's native format.
_TOOL_IMAGE_UNSUPPORTED_VENDORS = {"openai", "gemini", "google", "vertex_ai"}


async def resolve_resource_links_for_tool_message(
    tool_result: Any, vendor: str
) -> list[dict]:
    """Resolve resource_links for inclusion in a tool result message.

    For vendors that support images in tool messages (e.g., Anthropic/Claude),
    this returns the full multimodal content (text + image parts).

    For vendors that do NOT support images in tool messages (OpenAI, Gemini),
    this returns text-only content with descriptive placeholders instead of
    image data.  The actual image should be injected via a separate user
    message using ``resolve_media_as_user_message()``.

    Args:
        tool_result: The raw tool result (could be dict, list, string, etc.)
        vendor: One of "anthropic", "openai", "gemini".

    Returns:
        List of content dicts suitable for a tool result message.
    """
    if vendor not in _TOOL_IMAGE_UNSUPPORTED_VENDORS:
        # Claude and other vendors that support images inline in tool messages
        return await resolve_resource_links(tool_result, vendor)

    # For OpenAI/Gemini: resolve but replace image parts with text placeholders
    parts = await resolve_resource_links(tool_result, vendor)
    text_only: list[dict] = []
    for part in parts:
        if part.get("type") in ("image", "image_url"):
            text_only.append(
                {"type": "text", "text": "[Image content — see next message]"}
            )
        else:
            text_only.append(part)
    return text_only


async def resolve_media_as_user_message(
    tool_result: Any, vendor: str
) -> dict | None:
    """Return a user message containing resolved images from a tool result.

    For vendors that do NOT support images in tool messages (OpenAI, Gemini),
    this resolves resource_link items and packages the image parts into a
    ``role: "user"`` message that can be appended after the tool result message.

    For vendors that support images in tool messages (Anthropic), returns None
    because the image is already included in the tool result message.

    Args:
        tool_result: The raw tool result (could be dict, list, string, etc.)
        vendor: One of "anthropic", "openai", "gemini".

    Returns:
        A user message dict with image content, or None if not needed.
    """
    if vendor not in _TOOL_IMAGE_UNSUPPORTED_VENDORS:
        return None

    parts = await resolve_resource_links(tool_result, vendor)
    image_parts = [p for p in parts if p.get("type") in ("image", "image_url")]
    if not image_parts:
        return None

    content: list[dict] = [
        {"type": "text", "text": "The tool returned this image:"},
        *image_parts,
    ]
    return {"role": "user", "content": content}


def _has_resource_link(tool_result: Any) -> bool:
    """Quick check whether a tool result contains any resource_link items.

    This is a lightweight check used to decide whether the more expensive
    async resolution is needed.
    """
    if isinstance(tool_result, dict):
        if tool_result.get("type") == "resource_link":
            return True
        if tool_result.get("type") == "multi_content":
            items = tool_result.get("items") or tool_result.get("content") or []
            return any(
                isinstance(i, dict) and i.get("type") == "resource_link"
                for i in items
            )
    return False

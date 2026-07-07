"""Shared FastMCP transport-security override (single source of truth).

Leaf module (no mesh imports) so every ``http_app()`` call site can spread the
same kwargs without circular-import risk. See issue #1312.
"""

# host_origin_protection: mesh is an internal service mesh addressed by k8s
# Service DNS; the FastMCP DNS-rebinding (browser) host guard 421s any
# non-localhost Host. Disable it everywhere. Single source of truth so a new
# http_app() call site can't silently drop it. See issue #1312.
FASTMCP_TRANSPORT_SECURITY_KWARGS = {"host_origin_protection": False}

"""Read-only MCP server over stdio for the allowlisted agent surface (ADR 0014)."""

from .server import (
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_INSTRUCTIONS,
    MCP_SERVER_NAME,
    CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV,
    CONTEXT_EGRESS_NOTICE,
    McpStdioServer,
    handle_message,
)

__all__ = (
    "CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV",
    "CONTEXT_EGRESS_NOTICE",
    "MCP_PROTOCOL_VERSION",
    "MCP_SERVER_INSTRUCTIONS",
    "MCP_SERVER_NAME",
    "McpStdioServer",
    "handle_message",
)

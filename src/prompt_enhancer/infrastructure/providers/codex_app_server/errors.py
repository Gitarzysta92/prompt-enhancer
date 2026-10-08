"""Sanitized failures for the Codex App Server compatibility boundary."""

from __future__ import annotations


class CodexAdapterError(RuntimeError):
    """Base error whose message is safe to display or log."""


class CodexLifecycleError(CodexAdapterError):
    """The adapter was used before a successful probe or after closing."""


class CodexTransportError(CodexAdapterError):
    """The local stdio transport could not complete an operation."""


class CodexTransportTimeout(CodexTransportError):
    """A bounded local transport operation timed out."""


class CodexProtocolViolation(CodexAdapterError):
    """The peer violated the deliberately narrow read-only protocol."""


class CodexRequestRejected(CodexAdapterError):
    """The peer rejected an allowlisted request without exposing error content."""


class CodexCompatibilityError(CodexAdapterError):
    """The provider response does not match the supported schema family."""


class CodexNoAnalyzableTextError(CodexAdapterError):
    """The selected thread has no supported user text to analyze."""


class CodexScopeError(CodexAdapterError):
    """A read escaped the current, explicitly listed snapshot."""


class CodexLimitError(CodexAdapterError):
    """A configured privacy or resource bound was reached."""


class CodexSelectionLimitError(CodexLimitError):
    """The bounded provider-session selection scan could not complete."""


class CodexResponseLimitError(CodexLimitError):
    """A provider response exceeded the local transport frame bound."""


class CodexThreadStructureLimitError(CodexLimitError):
    """A selected thread exceeded the allowlisted parser's structural bounds."""


class CodexPreviewWindowLimitError(CodexLimitError):
    """The selected focus message could not fit in the fixed preview window."""

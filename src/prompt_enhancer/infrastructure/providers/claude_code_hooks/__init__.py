"""Claude Code hook-based provider surface.

Prospective, content-free capture: Claude Code invokes the receiver for each
lifecycle event; the receiver minimizes the payload in-process and appends to
an append-only ledger; the adapter reads that ledger through the ordinary
``ProviderAdapter`` port.  Nothing here reads a transcript, a settings file, or
any path under the provider's private directory.
"""

from .contracts import (
    ADAPTER_VERSION,
    CONTRACT_VERSION,
    HOOK_INSTALLATION_MARKER,
    RECEIVER_VERSION,
    SOURCE_SCHEMA_VERSION,
    HookEventName,
    MinimizedHookEvent,
    categorize_tool_name,
)
from .ledger import (
    HookLedgerConsentInactive,
    HookLedgerSnapshotError,
    HookLedgerUnavailable,
    LEDGER_READ_BOUNDARY_VERSION,
    LEDGER_SCHEMA_VERSION,
    LedgerEvent,
    LedgerReadBoundary,
    LedgerSession,
    LedgerSessionSnapshot,
    SqliteClaudeHookLedger,
    ledger_read_boundary_fingerprint,
    receiver_append,
    validate_ledger_session_snapshot,
)
from .r7_readiness import (
    CLAUDE_HOOKS_R7_READINESS_VERSION,
    ClaudeHookDescriptorValidation,
    ClaudeHookEphemeralDescriptorBatch,
    ClaudeHooksR7Blocker,
    ClaudeHooksR7ReadinessReceipt,
    build_claude_hooks_r7_readiness,
    validate_ephemeral_descriptor_batch,
)
from .receiver import (
    ALLOWED_PAYLOAD_KEYS,
    ReceiverOutcome,
    ReceiverStatus,
    minimize_payload,
    receive,
)

__all__ = (
    "ADAPTER_VERSION",
    "ALLOWED_PAYLOAD_KEYS",
    "CONTRACT_VERSION",
    "HOOK_INSTALLATION_MARKER",
    "HookEventName",
    "HookLedgerConsentInactive",
    "HookLedgerSnapshotError",
    "HookLedgerUnavailable",
    "LEDGER_READ_BOUNDARY_VERSION",
    "LEDGER_SCHEMA_VERSION",
    "LedgerEvent",
    "LedgerReadBoundary",
    "LedgerSession",
    "LedgerSessionSnapshot",
    "MinimizedHookEvent",
    "RECEIVER_VERSION",
    "ReceiverOutcome",
    "ReceiverStatus",
    "SOURCE_SCHEMA_VERSION",
    "SqliteClaudeHookLedger",
    "CLAUDE_HOOKS_R7_READINESS_VERSION",
    "ClaudeHookDescriptorValidation",
    "ClaudeHookEphemeralDescriptorBatch",
    "ClaudeHooksR7Blocker",
    "ClaudeHooksR7ReadinessReceipt",
    "build_claude_hooks_r7_readiness",
    "categorize_tool_name",
    "ledger_read_boundary_fingerprint",
    "minimize_payload",
    "receive",
    "receiver_append",
    "validate_ephemeral_descriptor_batch",
    "validate_ledger_session_snapshot",
)

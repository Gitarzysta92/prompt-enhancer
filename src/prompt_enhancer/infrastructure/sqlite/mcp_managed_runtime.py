"""SQLite content-free receipt store for approval-bound managed MCP calls."""

from __future__ import annotations

from datetime import UTC, datetime
import sqlite3
import threading

from ...application.agent_catalog import AgentCatalogError
from ...application.mcp_managed_runtime import (
    McpManagedHostCleanupEvidence,
    McpManagedRuntimeError,
    McpManagedToolCallClaim,
    McpManagedToolCallReceipt,
)
from ...application.mcp_managed_host import (
    McpManagedHostActionReceipt,
    McpManagedHostBinding,
    McpManagedHostCleanupBlock,
)
from .agent_catalog import AgentCatalogSqliteDatabase, _iso, _time


class SqliteMcpManagedRuntimeReceiptRepository:
    """Persist only fixed identities, revisions, digests, counts, and truth."""

    def __init__(self, database: AgentCatalogSqliteDatabase) -> None:
        self._database = database
        self._write_lock = threading.Lock()

    @staticmethod
    def _receipt(row: sqlite3.Row) -> McpManagedToolCallReceipt:
        try:
            return McpManagedToolCallReceipt(
                call_id=str(row["call_id"]),
                management_id=str(row["management_id"]),
                project_id=str(row["project_id"]),
                session_id=str(row["session_id"]),
                turn_id=str(row["turn_id"]),
                host_instance_id=str(row["host_instance_id"]),
                tool_snapshot_id=str(row["tool_snapshot_id"]),
                tool_id=str(row["tool_id"]),
                server_revision=int(row["server_revision"]),
                project_binding_revision=int(row["project_binding_revision"]),
                argument_digest=str(row["argument_digest"]),
                argument_bytes=int(row["argument_bytes"]),
                approval_state=str(row["approval_state"]),
                outcome=str(row["outcome"]),
                error_code=(
                    None if row["error_code"] is None else str(row["error_code"])
                ),
                requested_at=_time(str(row["requested_at"])),
                completed_at=_time(str(row["completed_at"])),
                result_bytes=int(row["result_bytes"]),
                result_digest=(
                    None
                    if row["result_digest"] is None
                    else str(row["result_digest"])
                ),
                cleanup_verified=bool(row["cleanup_verified"]),
                arguments_persisted=bool(row["arguments_persisted"]),
                result_persisted=bool(row["result_persisted"]),
                credentials_persisted=bool(row["credentials_persisted"]),
                reusable_approval_persisted=bool(
                    row["reusable_approval_persisted"]
                ),
            )
        except Exception:
            raise McpManagedRuntimeError("mcp_tool_receipt_storage_corrupt") from None

    @staticmethod
    def _claim(row: sqlite3.Row) -> McpManagedToolCallClaim:
        try:
            return McpManagedToolCallClaim(
                call_id=str(row["call_id"]),
                app_run_digest=str(row["app_run_digest"]),
                management_id=str(row["management_id"]),
                project_id=str(row["project_id"]),
                session_id=str(row["session_id"]),
                turn_id=str(row["turn_id"]),
                host_instance_id=str(row["host_instance_id"]),
                tool_snapshot_id=str(row["tool_snapshot_id"]),
                tool_id=str(row["tool_id"]),
                server_revision=int(row["server_revision"]),
                project_binding_revision=int(row["project_binding_revision"]),
                argument_digest=str(row["argument_digest"]),
                argument_bytes=int(row["argument_bytes"]),
                approval_digest=str(row["approval_digest"]),
                approval_state=str(row["approval_state"]),
                requested_at=_time(str(row["requested_at"])),
                approval_expires_at=_time(str(row["approval_expires_at"])),
                claimed_at=_time(str(row["claimed_at"])),
                arguments_persisted=bool(row["arguments_persisted"]),
                result_persisted=bool(row["result_persisted"]),
                approval_identifier_persisted=bool(
                    row["approval_identifier_persisted"]
                ),
                replay_grants_authority=bool(row["replay_grants_authority"]),
            )
        except Exception:
            raise McpManagedRuntimeError("mcp_tool_claim_storage_corrupt") from None

    @staticmethod
    def _claim_matches_receipt(
        claim: McpManagedToolCallClaim,
        receipt: McpManagedToolCallReceipt,
    ) -> bool:
        return (
            claim.call_id == receipt.call_id
            and claim.management_id == receipt.management_id
            and claim.project_id == receipt.project_id
            and claim.session_id == receipt.session_id
            and claim.turn_id == receipt.turn_id
            and claim.host_instance_id == receipt.host_instance_id
            and claim.tool_snapshot_id == receipt.tool_snapshot_id
            and claim.tool_id == receipt.tool_id
            and claim.server_revision == receipt.server_revision
            and claim.project_binding_revision == receipt.project_binding_revision
            and claim.argument_digest == receipt.argument_digest
            and claim.argument_bytes == receipt.argument_bytes
            and claim.approval_state == receipt.approval_state
            and claim.requested_at == receipt.requested_at
        )

    @staticmethod
    def _host_action_receipt(row: sqlite3.Row) -> McpManagedHostActionReceipt:
        try:
            return McpManagedHostActionReceipt(
                receipt_id=str(row["receipt_id"]),
                request_id=str(row["request_id"]),
                management_id=str(row["management_id"]),
                project_id=str(row["project_id"]),
                instance_id=(
                    None if row["instance_id"] is None else str(row["instance_id"])
                ),
                app_run_digest=str(row["app_run_digest"]),
                binding_digest=str(row["binding_digest"]),
                execution_kind=str(row["execution_kind"]),
                action=str(row["action"]),
                outcome=str(row["outcome"]),
                reason=str(row["reason"]),
                requested_at=_time(str(row["requested_at"])),
                completed_at=_time(str(row["completed_at"])),
                process_started=bool(row["process_started"]),
                cleanup_state=str(row["cleanup_state"]),
                host_ready=bool(row["host_ready"]),
                error_code=(
                    None if row["error_code"] is None else str(row["error_code"])
                ),
                endpoint_persisted=bool(row["endpoint_persisted"]),
                credential_persisted=bool(row["credential_persisted"]),
                command_or_path_persisted=bool(row["command_or_path_persisted"]),
                tool_content_persisted=bool(row["tool_content_persisted"]),
                prompt_or_result_persisted=bool(
                    row["prompt_or_result_persisted"]
                ),
                replay_grants_authority=bool(row["replay_grants_authority"]),
            )
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_host_action_receipt_storage_corrupt"
            ) from None

    @staticmethod
    def _cleanup_evidence(row: sqlite3.Row) -> McpManagedHostCleanupEvidence:
        try:
            block = McpManagedHostCleanupBlock(
                block_id=str(row["block_id"]),
                management_id=str(row["management_id"]),
                project_id=str(row["project_id"]),
                instance_id=str(row["instance_id"]),
                app_run_digest=str(row["app_run_digest"]),
                binding_digest=str(row["binding_digest"]),
                reason=str(row["reason"]),
                state=str(row["state"]),
                process_started=bool(row["process_started"]),
                cleanup_verified=bool(row["cleanup_verified"]),
                lifecycle_actions_blocked=bool(row["lifecycle_actions_blocked"]),
                recovery_attempts=int(row["recovery_attempts"]),
                created_at=_time(str(row["created_at"])),
                updated_at=_time(str(row["updated_at"])),
                resolved_at=(
                    None if row["resolved_at"] is None else _time(str(row["resolved_at"]))
                ),
                endpoint_persisted=bool(row["endpoint_persisted"]),
                credential_persisted=bool(row["credential_persisted"]),
                process_identity_persisted=bool(row["process_identity_persisted"]),
                command_or_path_persisted=bool(row["command_or_path_persisted"]),
                tool_content_persisted=bool(row["tool_content_persisted"]),
            )
            binding = McpManagedHostBinding.model_validate_json(
                str(row["binding_json"])
            )
            return McpManagedHostCleanupEvidence(block=block, binding=binding)
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_host_cleanup_evidence_storage_corrupt"
            ) from None

    def get_tool_call_claim(
        self,
        call_id: str,
    ) -> McpManagedToolCallClaim | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM mcp_managed_tool_call_claims WHERE call_id=?",
                    (call_id,),
                ).fetchone()
                return None if row is None else self._claim(row)
        except McpManagedRuntimeError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError(
                "mcp_tool_claim_storage_unavailable"
            ) from None

    def claim_tool_call(self, claim: McpManagedToolCallClaim) -> bool:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                settled = connection.execute(
                    "SELECT 1 FROM mcp_managed_tool_call_receipts WHERE call_id=?",
                    (claim.call_id,),
                ).fetchone()
                if settled is not None:
                    connection.execute("COMMIT")
                    return False
                existing = connection.execute(
                    "SELECT * FROM mcp_managed_tool_call_claims WHERE call_id=?",
                    (claim.call_id,),
                ).fetchone()
                if existing is not None:
                    if self._claim(existing) != claim:
                        connection.execute("ROLLBACK")
                        raise McpManagedRuntimeError("mcp_tool_claim_conflict")
                    connection.execute("COMMIT")
                    return False
                scoped_session = connection.execute(
                    """
                    SELECT 1
                    FROM agent_catalog_sessions
                    WHERE session_id=? AND project_id=?
                    """,
                    (claim.session_id, claim.project_id),
                ).fetchone()
                if scoped_session is None:
                    connection.execute("ROLLBACK")
                    raise McpManagedRuntimeError("mcp_tool_claim_binding_invalid")
                connection.execute(
                    """
                    INSERT INTO mcp_managed_tool_call_claims(
                        call_id,app_run_digest,management_id,project_id,session_id,
                        turn_id,host_instance_id,tool_snapshot_id,tool_id,
                        server_revision,project_binding_revision,argument_digest,
                        argument_bytes,approval_digest,approval_state,requested_at,
                        approval_expires_at,claimed_at,arguments_persisted,
                        result_persisted,approval_identifier_persisted,
                        replay_grants_authority
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,0)
                    """,
                    (
                        claim.call_id,
                        claim.app_run_digest,
                        claim.management_id,
                        claim.project_id,
                        claim.session_id,
                        claim.turn_id,
                        claim.host_instance_id,
                        claim.tool_snapshot_id,
                        claim.tool_id,
                        claim.server_revision,
                        claim.project_binding_revision,
                        claim.argument_digest,
                        claim.argument_bytes,
                        claim.approval_digest,
                        claim.approval_state,
                        _iso(claim.requested_at),
                        _iso(claim.approval_expires_at),
                        _iso(claim.claimed_at),
                    ),
                )
                stored = connection.execute(
                    "SELECT * FROM mcp_managed_tool_call_claims WHERE call_id=?",
                    (claim.call_id,),
                ).fetchone()
                if stored is None or self._claim(stored) != claim:
                    connection.execute("ROLLBACK")
                    raise McpManagedRuntimeError("mcp_tool_claim_storage_corrupt")
                connection.execute("COMMIT")
                return True
        except McpManagedRuntimeError:
            raise
        except sqlite3.IntegrityError:
            raise McpManagedRuntimeError("mcp_tool_claim_binding_invalid") from None
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError(
                "mcp_tool_claim_storage_unavailable"
            ) from None

    def get_tool_call_receipt(
        self,
        call_id: str,
    ) -> McpManagedToolCallReceipt | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM mcp_managed_tool_call_receipts WHERE call_id=?",
                    (call_id,),
                ).fetchone()
                return None if row is None else self._receipt(row)
        except McpManagedRuntimeError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError("mcp_tool_receipt_storage_unavailable") from None

    def record_tool_call_receipt(self, receipt: McpManagedToolCallReceipt) -> None:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM mcp_managed_tool_call_receipts WHERE call_id=?",
                    (receipt.call_id,),
                ).fetchone()
                if existing is not None:
                    if self._receipt(existing) != receipt:
                        connection.execute("ROLLBACK")
                        raise McpManagedRuntimeError("mcp_tool_receipt_conflict")
                    connection.execute("COMMIT")
                    return
                claim_row = connection.execute(
                    "SELECT * FROM mcp_managed_tool_call_claims WHERE call_id=?",
                    (receipt.call_id,),
                ).fetchone()
                if claim_row is None:
                    connection.execute("ROLLBACK")
                    raise McpManagedRuntimeError("mcp_tool_claim_missing")
                if not self._claim_matches_receipt(self._claim(claim_row), receipt):
                    connection.execute("ROLLBACK")
                    raise McpManagedRuntimeError("mcp_tool_claim_conflict")
                connection.execute(
                    """
                    INSERT INTO mcp_managed_tool_call_receipts(
                        call_id,management_id,project_id,session_id,turn_id,
                        host_instance_id,tool_snapshot_id,tool_id,server_revision,
                        project_binding_revision,argument_digest,argument_bytes,
                        approval_state,outcome,error_code,requested_at,completed_at,
                        result_bytes,result_digest,cleanup_verified,
                        arguments_persisted,result_persisted,credentials_persisted,
                        reusable_approval_persisted
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,0)
                    """,
                    (
                        receipt.call_id,
                        receipt.management_id,
                        receipt.project_id,
                        receipt.session_id,
                        receipt.turn_id,
                        receipt.host_instance_id,
                        receipt.tool_snapshot_id,
                        receipt.tool_id,
                        receipt.server_revision,
                        receipt.project_binding_revision,
                        receipt.argument_digest,
                        receipt.argument_bytes,
                        receipt.approval_state,
                        receipt.outcome,
                        receipt.error_code,
                        _iso(receipt.requested_at),
                        _iso(receipt.completed_at),
                        receipt.result_bytes,
                        receipt.result_digest,
                        int(receipt.cleanup_verified),
                    ),
                )
                stored = connection.execute(
                    "SELECT * FROM mcp_managed_tool_call_receipts WHERE call_id=?",
                    (receipt.call_id,),
                ).fetchone()
                if stored is None or self._receipt(stored) != receipt:
                    connection.execute("ROLLBACK")
                    raise McpManagedRuntimeError("mcp_tool_receipt_storage_corrupt")
                connection.execute("COMMIT")
        except McpManagedRuntimeError:
            raise
        except sqlite3.IntegrityError:
            raise McpManagedRuntimeError("mcp_tool_receipt_binding_invalid") from None
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError("mcp_tool_receipt_storage_unavailable") from None

    def reconcile_interrupted_tool_calls(
        self,
        *,
        current_app_run_digest: str,
        interrupted_at: datetime,
    ) -> tuple[McpManagedToolCallReceipt, ...]:
        """Settle claims from earlier app runs without retaining call content.

        A claim proves that a one-use native decision was consumed, but an
        absent receipt cannot prove that an approved external call completed.
        Approved orphaned claims therefore fail with explicit interruption and
        unverified cleanup. Decisions that never invoke a tool keep their exact
        denial/timeout/cancellation truth.
        """

        if (
            len(current_app_run_digest) != 64
            or any(character not in "0123456789abcdef" for character in current_app_run_digest)
            or interrupted_at.tzinfo is None
            or interrupted_at.utcoffset() is None
        ):
            raise McpManagedRuntimeError(
                "mcp_tool_restart_reconciliation_invalid"
            )
        observed_at = interrupted_at.astimezone(UTC)
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT claim.*
                    FROM mcp_managed_tool_call_claims claim
                    LEFT JOIN mcp_managed_tool_call_receipts receipt
                      ON receipt.call_id=claim.call_id
                    WHERE claim.app_run_digest!=? AND receipt.call_id IS NULL
                    ORDER BY claim.claimed_at,claim.call_id
                    """,
                    (current_app_run_digest,),
                ).fetchall()
                receipts: list[McpManagedToolCallReceipt] = []
                for row in rows:
                    claim = self._claim(row)
                    outcome_by_decision = {
                        "denied": "denied",
                        "timed_out": "timed_out",
                        "cancelled_before_decision": "cancelled",
                    }
                    approved = claim.approval_state == "approved"
                    receipt = McpManagedToolCallReceipt(
                        call_id=claim.call_id,
                        management_id=claim.management_id,
                        project_id=claim.project_id,
                        session_id=claim.session_id,
                        turn_id=claim.turn_id,
                        host_instance_id=claim.host_instance_id,
                        tool_snapshot_id=claim.tool_snapshot_id,
                        tool_id=claim.tool_id,
                        server_revision=claim.server_revision,
                        project_binding_revision=claim.project_binding_revision,
                        argument_digest=claim.argument_digest,
                        argument_bytes=claim.argument_bytes,
                        approval_state=claim.approval_state,
                        outcome=(
                            "failed"
                            if approved
                            else outcome_by_decision[claim.approval_state]
                        ),
                        error_code=(
                            "mcp_tool_call_interrupted" if approved else None
                        ),
                        requested_at=claim.requested_at,
                        completed_at=max(observed_at, claim.claimed_at),
                        result_bytes=0,
                        result_digest=None,
                        cleanup_verified=not approved,
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_tool_call_receipts(
                            call_id,management_id,project_id,session_id,turn_id,
                            host_instance_id,tool_snapshot_id,tool_id,
                            server_revision,project_binding_revision,
                            argument_digest,argument_bytes,approval_state,outcome,
                            error_code,requested_at,completed_at,result_bytes,
                            result_digest,cleanup_verified,arguments_persisted,
                            result_persisted,credentials_persisted,
                            reusable_approval_persisted
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,0)
                        """,
                        (
                            receipt.call_id,
                            receipt.management_id,
                            receipt.project_id,
                            receipt.session_id,
                            receipt.turn_id,
                            receipt.host_instance_id,
                            receipt.tool_snapshot_id,
                            receipt.tool_id,
                            receipt.server_revision,
                            receipt.project_binding_revision,
                            receipt.argument_digest,
                            receipt.argument_bytes,
                            receipt.approval_state,
                            receipt.outcome,
                            receipt.error_code,
                            _iso(receipt.requested_at),
                            _iso(receipt.completed_at),
                            receipt.result_bytes,
                            receipt.result_digest,
                            int(receipt.cleanup_verified),
                        ),
                    )
                    receipts.append(receipt)
                connection.execute("COMMIT")
                return tuple(receipts)
        except McpManagedRuntimeError:
            raise
        except sqlite3.IntegrityError:
            raise McpManagedRuntimeError(
                "mcp_tool_restart_reconciliation_conflict"
            ) from None
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError(
                "mcp_tool_restart_reconciliation_unavailable"
            ) from None

    def get_host_action_receipt(
        self,
        request_id: str,
    ) -> McpManagedHostActionReceipt | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM mcp_managed_host_action_receipts WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                return None if row is None else self._host_action_receipt(row)
        except McpManagedRuntimeError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError(
                "mcp_host_action_receipt_storage_unavailable"
            ) from None

    def record_host_action_receipt(
        self,
        receipt: McpManagedHostActionReceipt,
    ) -> None:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM mcp_managed_host_action_receipts WHERE request_id=?",
                    (receipt.request_id,),
                ).fetchone()
                if existing is not None:
                    if self._host_action_receipt(existing) != receipt:
                        connection.execute("ROLLBACK")
                        raise McpManagedRuntimeError(
                            "mcp_host_action_receipt_conflict"
                        )
                    connection.execute("COMMIT")
                    return
                connection.execute(
                    """
                    INSERT INTO mcp_managed_host_action_receipts(
                        receipt_id,request_id,management_id,project_id,instance_id,
                        app_run_digest,binding_digest,execution_kind,action,outcome,
                        reason,requested_at,completed_at,process_started,
                        cleanup_state,host_ready,error_code,endpoint_persisted,
                        credential_persisted,command_or_path_persisted,
                        tool_content_persisted,prompt_or_result_persisted,
                        replay_grants_authority
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,0,0,0)
                    """,
                    (
                        receipt.receipt_id,
                        receipt.request_id,
                        receipt.management_id,
                        receipt.project_id,
                        receipt.instance_id,
                        receipt.app_run_digest,
                        receipt.binding_digest,
                        receipt.execution_kind,
                        receipt.action,
                        receipt.outcome,
                        receipt.reason,
                        _iso(receipt.requested_at),
                        _iso(receipt.completed_at),
                        int(receipt.process_started),
                        receipt.cleanup_state,
                        int(receipt.host_ready),
                        receipt.error_code,
                    ),
                )
                stored = connection.execute(
                    "SELECT * FROM mcp_managed_host_action_receipts WHERE request_id=?",
                    (receipt.request_id,),
                ).fetchone()
                if stored is None or self._host_action_receipt(stored) != receipt:
                    connection.execute("ROLLBACK")
                    raise McpManagedRuntimeError(
                        "mcp_host_action_receipt_storage_corrupt"
                    )
                connection.execute("COMMIT")
        except McpManagedRuntimeError:
            raise
        except sqlite3.IntegrityError:
            raise McpManagedRuntimeError(
                "mcp_host_action_receipt_binding_invalid"
            ) from None
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError(
                "mcp_host_action_receipt_storage_unavailable"
            ) from None

    def get_active_cleanup_evidence(
        self,
        management_id: str,
        project_id: str,
    ) -> McpManagedHostCleanupEvidence | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM mcp_managed_host_cleanup_blocks
                    WHERE management_id=? AND project_id=? AND state='active'
                    """,
                    (management_id, project_id),
                ).fetchone()
                return None if row is None else self._cleanup_evidence(row)
        except McpManagedRuntimeError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError(
                "mcp_host_cleanup_evidence_storage_unavailable"
            ) from None

    def record_cleanup_evidence(
        self,
        evidence: McpManagedHostCleanupEvidence,
    ) -> None:
        binding_json = evidence.binding.model_dump_json()
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM mcp_managed_host_cleanup_blocks WHERE block_id=?",
                    (evidence.block.block_id,),
                ).fetchone()
                if existing is not None:
                    if self._cleanup_evidence(existing) != evidence:
                        connection.execute("ROLLBACK")
                        raise McpManagedRuntimeError(
                            "mcp_host_cleanup_evidence_conflict"
                        )
                    connection.execute("COMMIT")
                    return
                block = evidence.block
                connection.execute(
                    """
                    INSERT INTO mcp_managed_host_cleanup_blocks(
                        block_id,management_id,project_id,instance_id,
                        app_run_digest,binding_digest,binding_json,reason,state,
                        process_started,cleanup_verified,lifecycle_actions_blocked,
                        recovery_attempts,created_at,updated_at,resolved_at,
                        endpoint_persisted,credential_persisted,
                        process_identity_persisted,command_or_path_persisted,
                        tool_content_persisted
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,0,0)
                    """,
                    (
                        block.block_id,
                        block.management_id,
                        block.project_id,
                        block.instance_id,
                        block.app_run_digest,
                        block.binding_digest,
                        binding_json,
                        block.reason,
                        block.state,
                        int(block.process_started),
                        int(block.cleanup_verified),
                        int(block.lifecycle_actions_blocked),
                        block.recovery_attempts,
                        _iso(block.created_at),
                        _iso(block.updated_at),
                        None if block.resolved_at is None else _iso(block.resolved_at),
                    ),
                )
                stored = connection.execute(
                    "SELECT * FROM mcp_managed_host_cleanup_blocks WHERE block_id=?",
                    (block.block_id,),
                ).fetchone()
                if stored is None or self._cleanup_evidence(stored) != evidence:
                    connection.execute("ROLLBACK")
                    raise McpManagedRuntimeError(
                        "mcp_host_cleanup_evidence_storage_corrupt"
                    )
                connection.execute("COMMIT")
        except McpManagedRuntimeError:
            raise
        except sqlite3.IntegrityError:
            raise McpManagedRuntimeError(
                "mcp_host_cleanup_evidence_conflict"
            ) from None
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedRuntimeError(
                "mcp_host_cleanup_evidence_storage_unavailable"
            ) from None


__all__ = ("SqliteMcpManagedRuntimeReceiptRepository",)

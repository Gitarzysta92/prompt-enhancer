"""Explicit, bounded, read-only Codex P1 text-analysis source.

Construction is inert.  The source creates a local App Server client only after
receiving a ``TEXT_ANALYSIS`` selector and matching local-only consent grant.
It returns the shared ephemeral analysis contract and has no persistence port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr

from ....application.analysis.text_contracts import (
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
    EphemeralRedactedActionDescriptor,
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextAnalysisScope,
    TextAnalysisScopeKind,
    TextAnalysisScopeReason,
    TextAnalysisScopeState,
    TextAnalysisPrivacyError,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from ....application.analysis.requirement_action_evidence import (
    requirement_action_candidate_metadata_fingerprint,
)
from ....application.analysis.text_source import (
    EphemeralTextAnalysisSource,
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceFailureReason,
    TextSourceReadError,
    TextSourceAccessGrant,
)
from ....application.ingestion import SourceIdentifierProtector
from ....domain import (
    DataTier,
    EventKind,
    Provider,
    SAFE_VERSION_PATTERN,
)
from ...language import DeterministicEnglishPolishDetector
from ...redaction import DeterministicLocalRedactor, RedactedText
from .client import CodexAppServerClient, CodexServerInfo
from .content_contracts import (
    TEXT_CONTENT_ADAPTER_VERSION,
    TEXT_CONTENT_SCHEMA_VERSION,
    CodexTextContentLimits,
    CodexTextItemKind,
    RawCodexTextThread,
)
from .contracts import RawThreadPage, SOURCE_SCHEMA_VERSION
from .errors import (
    CodexAdapterError,
    CodexCompatibilityError,
    CodexLimitError,
    CodexNoAnalyzableTextError,
    CodexProtocolViolation,
    CodexPreviewWindowLimitError,
    CodexResponseLimitError,
    CodexRequestRejected,
    CodexSelectionLimitError,
    CodexScopeError,
    CodexThreadStructureLimitError,
    CodexTransportTimeout,
)
from .limits import CodexReadLimits
from .transports.stdio_jsonl import StdioJsonRpcTransport, ThreadReadPolicy


CODEX_LOCAL_INSTALLATION_ID = "codex-app-server-local"

CodexContentAccessPurpose = TextAnalysisPurpose
CodexTextAnalysisSelection = TextAnalysisSelection
CodexTextAccessGrant = TextSourceAccessGrant


class LocalTextRedactor(Protocol):
    version: str

    def redact(self, value: SecretStr) -> RedactedText: ...


class LocalTextLanguageDetector(Protocol):
    version: str

    def detect(self, value: SecretStr) -> TextLanguage: ...


class CodexTextClient(Protocol):
    def initialize(self) -> CodexServerInfo: ...

    def list_threads(
        self,
        *,
        cursor: str | None,
        limit: int,
        new_snapshot: bool,
    ) -> RawThreadPage: ...

    def read_thread_text_analysis(self, thread_id: str) -> RawCodexTextThread: ...

    def close(self) -> None: ...


TextClientFactory = Callable[[], CodexTextClient]


@dataclass(frozen=True, slots=True)
class _CandidateMessage:
    message_id: str
    sequence: int
    role: TextRole
    kind: TextMessageKind
    language: TextLanguage
    text: SecretStr


CODEX_AVAILABLE_MESSAGE_KINDS = frozenset(
    {
        TextMessageKind.REQUEST,
        TextMessageKind.RESPONSE,
        TextMessageKind.PLAN,
        # A user message after locally observed agent activity is a typed
        # follow-up/feedback opportunity.  This is derived from chronology and
        # role only; no private text is inspected to mint the capability.
        TextMessageKind.FEEDBACK,
    }
)


def _encode_identity(*components: str) -> str:
    return "".join(f"{len(component)}:{component}" for component in components)


def _bounded_provider_identifier(value: str) -> str:
    if not value or len(value) > 4_096 or "\x00" in value:
        raise CodexCompatibilityError("provider session identifier is invalid")
    return value


class CodexTextAnalysisSource(EphemeralTextAnalysisSource):
    """Map one selected App Server thread into an ephemeral redacted window."""

    provider = Provider.CODEX
    purpose = TextAnalysisPurpose.TEXT_ANALYSIS
    read_only = True
    requires_explicit_selection = True
    # Provenance identities a provider-specific subclass overrides.
    text_adapter_version = TEXT_CONTENT_ADAPTER_VERSION
    text_source_schema_version = SOURCE_SCHEMA_VERSION

    def __init__(
        self,
        pseudonymizer: SourceIdentifierProtector,
        *,
        redactor: LocalTextRedactor | None = None,
        language_detector: LocalTextLanguageDetector | None = None,
        limits: CodexReadLimits | None = None,
        text_limits: CodexTextContentLimits | None = None,
        client_factory: TextClientFactory | None = None,
    ) -> None:
        self._pseudonymizer = pseudonymizer
        self._redactor = redactor or DeterministicLocalRedactor()
        self._language_detector = (
            language_detector or DeterministicEnglishPolishDetector()
        )
        self._content_schema_version = (
            f"{TEXT_CONTENT_SCHEMA_VERSION}+{self._language_detector.version}"
        )
        if SAFE_VERSION_PATTERN.fullmatch(self._content_schema_version) is None:
            raise ValueError("language detector version cannot form safe provenance")
        self._limits = limits or CodexReadLimits()
        self._text_limits = text_limits or CodexTextContentLimits()
        self._client_factory = client_factory or self._default_client_factory

    def _default_client_factory(self) -> CodexAppServerClient:
        return CodexAppServerClient(
            StdioJsonRpcTransport(
                limits=self._limits,
                thread_read_policy=ThreadReadPolicy.TEXT_ANALYSIS,
            ),
            limits=self._limits,
            text_limits=self._text_limits,
        )

    def read_raw_thread(self, selected_session_id: str):
        """Owner-authorized on-demand read of one listed thread, unredacted.

        Used only by the session reader (ADR 0011).  Same client, snapshot
        scope, and selection rules as :meth:`read`; the caller receives the
        raw thread and the server info and must persist neither.
        """

        client: CodexTextClient | None = None
        try:
            client = self._client_factory()
            server_info = client.initialize()
            thread = self._find_and_read_selected(client, selected_session_id)
            return thread, server_info
        finally:
            if client is not None:
                client.close()

    def read(
        self,
        *,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
        task_profile: TextTaskProfile,
    ) -> P1TextAnalysisInput:
        """Perform one local read after capability and selector checks."""

        self._require_matching_grant(selection, grant)
        client: CodexTextClient | None = None
        try:
            client = self._client_factory()
            server_info = client.initialize()
            thread = self._find_and_read_selected(client, selection.session_id)
            return self._analysis_input(
                thread=thread,
                selection=selection,
                task_profile=task_profile,
                server_info=server_info,
            )
        except CodexTransportTimeout:
            raise TextSourceReadError(TextSourceFailureReason.TIMEOUT) from None
        except CodexScopeError:
            raise TextSourceReadError(
                TextSourceFailureReason.SELECTION_SNAPSHOT_MISS
            ) from None
        except CodexSelectionLimitError:
            raise TextSourceReadError(
                TextSourceFailureReason.SELECTION_LIMIT
            ) from None
        except CodexResponseLimitError:
            raise TextSourceReadError(
                TextSourceFailureReason.PROVIDER_RESPONSE_LIMIT
            ) from None
        except CodexThreadStructureLimitError:
            raise TextSourceReadError(
                TextSourceFailureReason.THREAD_STRUCTURE_LIMIT
            ) from None
        except CodexPreviewWindowLimitError:
            raise TextSourceReadError(
                TextSourceFailureReason.PREVIEW_WINDOW_LIMIT
            ) from None
        except CodexLimitError:
            raise TextSourceReadError(TextSourceFailureReason.RESOURCE_LIMIT) from None
        except CodexNoAnalyzableTextError:
            raise TextSourceReadError(
                TextSourceFailureReason.NO_ANALYZABLE_TEXT
            ) from None
        except CodexCompatibilityError:
            raise TextSourceReadError(
                TextSourceFailureReason.SCHEMA_UNSUPPORTED
            ) from None
        except (CodexProtocolViolation, CodexRequestRejected):
            raise TextSourceReadError(
                TextSourceFailureReason.PROTOCOL_REJECTED
            ) from None
        except CodexAdapterError:
            raise TextSourceReadError(
                TextSourceFailureReason.PROVIDER_UNAVAILABLE
            ) from None
        except TextSourceReadError:
            raise
        except Exception:
            # Factories, redactors, and detectors are provider-side
            # implementations. Their private failures cannot cross this port.
            raise TextSourceReadError(
                TextSourceFailureReason.PROVIDER_UNAVAILABLE
            ) from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    # Provider cleanup failures can contain process details.  They
                    # cannot replace the sanitized result or source error.
                    pass

    def _require_matching_grant(
        self,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
    ) -> None:
        if selection.purpose is not self.purpose:
            raise TextAnalysisPrivacyError("content access purpose is not allowed")
        if (
            selection.provider is not self.provider
            or grant.purpose is not selection.purpose
            or grant.provider is not selection.provider
            or grant.session_id != selection.session_id
            or grant.data_tier is not DataTier.REDACTED_CONTENT
            or not grant.per_run_confirmation_active
            or not grant.local_only
            or grant.content_persistence_allowed
        ):
            raise TextAnalysisPrivacyError(
                "local text-analysis capability does not match the selected session"
            )

    def _safe_session_id(self, raw_thread_id: str) -> str:
        raw_thread_id = _bounded_provider_identifier(raw_thread_id)
        installation_id = self._pseudonymizer.pseudonymize(
            "codex:installation", CODEX_LOCAL_INSTALLATION_ID
        )
        return self._pseudonymizer.pseudonymize(
            f"codex:session:{installation_id}", raw_thread_id
        )

    def _find_and_read_selected(
        self,
        client: CodexTextClient,
        selected_session_id: str,
    ) -> RawCodexTextThread:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        pages = 0
        sessions = 0
        while True:
            if pages >= self._limits.max_pages:
                raise CodexSelectionLimitError(
                    "text-analysis selection scan exceeded its page bound"
                )
            remaining = self._limits.max_sessions - sessions
            if remaining < 1:
                raise CodexSelectionLimitError(
                    "text-analysis selection scan exceeded its session bound"
                )
            try:
                page = client.list_threads(
                    cursor=cursor,
                    limit=min(self._limits.max_page_size, remaining),
                    new_snapshot=cursor is None,
                )
            except CodexLimitError:
                raise CodexSelectionLimitError(
                    "text-analysis selection page exceeded its bound"
                ) from None
            pages += 1
            sessions += len(page.threads)
            for listed in page.threads:
                raw_thread_id = listed.thread_id.get_secret_value()
                if self._safe_session_id(raw_thread_id) == selected_session_id:
                    return client.read_thread_text_analysis(raw_thread_id)

            next_cursor = (
                page.next_cursor.get_secret_value()
                if page.next_cursor is not None
                else None
            )
            if next_cursor is None:
                break
            if not next_cursor or len(next_cursor) > 4_096 or "\x00" in next_cursor:
                raise CodexCompatibilityError("provider pagination cursor is invalid")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise CodexScopeError("provider text-analysis pagination repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise CodexScopeError(
            "selected session was not present in the current provider snapshot"
        )

    def _analysis_input(
        self,
        *,
        thread: RawCodexTextThread,
        selection: TextAnalysisSelection,
        task_profile: TextTaskProfile,
        server_info: CodexServerInfo,
    ) -> P1TextAnalysisInput:
        candidates = self._redacted_candidates(thread, selection.session_id)
        if not candidates:
            raise CodexNoAnalyzableTextError(
                "selected session contains no allowlisted text"
            )
        user_positions = tuple(
            index
            for index, candidate in enumerate(candidates)
            if candidate.role is TextRole.USER
        )
        if not user_positions:
            raise CodexNoAnalyzableTextError(
                "selected session contains no analyzable user text"
            )
        focus_position = user_positions[-1]
        observed, left_boundary_closed = self._select_window(
            candidates,
            focus_position,
            selection,
        )
        if selection.scope_kind is TextAnalysisScopeKind.FULL_AVAILABLE_SESSION:
            # Full available-session scope never treats a saturated suffix as
            # equivalent to the requested session.  Both provider-history and
            # selected-window completeness must be proven.
            window_extraction_complete = (
                thread.extraction_complete and len(observed) == len(candidates)
            )
        else:
            # An explicitly requested recent window may be complete even when
            # older provider history lies outside that intentional boundary.
            window_extraction_complete = thread.extraction_complete or (
                thread.older_history_truncated
                and not thread.unclassified_omission
                and left_boundary_closed
            )
        scope_reasons = self._scope_incomplete_reasons(
            thread=thread,
            selection=selection,
            observed=observed,
            eligible_count=len(candidates),
            extraction_complete=window_extraction_complete,
        )
        analysis_scope = TextAnalysisScope(
            kind=selection.scope_kind,
            state=(
                TextAnalysisScopeState.COMPLETE
                if window_extraction_complete
                else TextAnalysisScopeState.INCOMPLETE_SOURCE
            ),
            requested_max_messages=selection.max_messages,
            requested_max_characters=selection.max_characters,
            source_history_complete=thread.extraction_complete,
            reason_codes=scope_reasons,
        )
        focus_message_id = candidates[focus_position].message_id
        messages = tuple(
            EphemeralRedactedMessage(
                message_id=candidate.message_id,
                sequence=candidate.sequence,
                role=candidate.role,
                kind=candidate.kind,
                language=candidate.language,
                text=candidate.text,
            )
            for candidate in observed
        )
        action_descriptors = self._redacted_action_descriptors(
            thread,
            selection.session_id,
        )
        fingerprint_payload = _encode_identity(
            selection.session_id,
            self._content_schema_version,
            self._redactor.version,
            _encode_identity(
                "analysis-scope",
                analysis_scope.kind.value,
                analysis_scope.state.value,
                str(analysis_scope.requested_max_messages),
                str(analysis_scope.requested_max_characters),
                str(analysis_scope.source_history_complete).casefold(),
                *(reason.value for reason in analysis_scope.reason_codes),
            ),
            _encode_identity(
                "window-text-extraction-complete",
                str(window_extraction_complete).casefold(),
            ),
            _encode_identity(
                "source-history-extraction-complete",
                str(thread.extraction_complete).casefold(),
            ),
            _encode_identity(
                "source-older-history-truncated",
                str(thread.older_history_truncated).casefold(),
            ),
            _encode_identity(
                "source-unclassified-omission",
                str(thread.unclassified_omission).casefold(),
            ),
            _encode_identity(
                "available-message-kinds",
                    *(
                        kind.value
                        for kind in sorted(
                            CODEX_AVAILABLE_MESSAGE_KINDS,
                            key=lambda item: item.value,
                        )
                    ),
            ),
            _encode_identity(
                "action-descriptor-algorithm",
                ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
                "complete",
                str(thread.action_descriptor_extraction_complete).casefold(),
                "descriptor-count",
                str(len(action_descriptors)),
            ),
            *(
                _encode_identity(
                    descriptor.source_reference_id,
                    descriptor.event_kind.value,
                    descriptor.tool_name.get_secret_value(),
                    descriptor.invocation_preview.get_secret_value(),
                    (
                        "none"
                        if descriptor.result_or_effect_preview is None
                        else descriptor.result_or_effect_preview.get_secret_value()
                    ),
                    str(descriptor.invocation_truncated).casefold(),
                    str(descriptor.result_or_effect_truncated).casefold(),
                    descriptor.redactor_version,
                    descriptor.candidate_metadata_fingerprint_version or "none",
                    descriptor.candidate_metadata_fingerprint or "none",
                )
                for descriptor in action_descriptors
            ),
            *(
                _encode_identity(
                    message.message_id,
                    str(message.sequence),
                    message.role.value,
                    message.kind.value,
                    message.text.get_secret_value(),
                )
                for message in messages
            ),
        )
        fingerprint = self._pseudonymizer.pseudonymize(
            f"codex:text-window:{selection.session_id}",
            fingerprint_payload,
        )
        return P1TextAnalysisInput(
            provider=self.provider,
            session_id=selection.session_id,
            provider_version=server_info.provider_version,
            adapter_version=self.text_adapter_version,
            source_schema_version=self.text_source_schema_version,
            content_schema_version=self._content_schema_version,
            redactor_version=self._redactor.version,
            analysis_scope=analysis_scope,
            text_extraction_complete=window_extraction_complete,
            available_message_kinds=CODEX_AVAILABLE_MESSAGE_KINDS,
            analysis_window_fingerprint=fingerprint,
            focus_message_id=focus_message_id,
            observed_message_count=len(messages),
            eligible_message_count=len(candidates),
            messages=messages,
            action_descriptor_algorithm_version=(
                ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
            ),
            action_descriptor_extraction_complete=(
                thread.action_descriptor_extraction_complete
            ),
            action_descriptors=action_descriptors,
            task_profile=task_profile,
        )

    def _redacted_action_descriptors(
        self,
        thread: RawCodexTextThread,
        safe_session_id: str,
    ) -> tuple[EphemeralRedactedActionDescriptor, ...]:
        """Redact private action details and bind them to persisted safe IDs."""

        descriptors: list[EphemeralRedactedActionDescriptor] = []
        for raw in thread.action_descriptors:
            source_reference_id = self._pseudonymizer.pseudonymize(
                f"{self.provider.value}:event:{safe_session_id}",
                raw.source_event_id.get_secret_value(),
            )
            event_kind = EventKind(raw.event_kind)
            candidate_metadata_fingerprint = None
            candidate_metadata_fingerprint_version = None
            if raw.candidate_metadata_complete:
                assert raw.candidate_sequence is not None
                assert raw.candidate_occurred_at is not None
                assert raw.candidate_family is not None
                assert raw.candidate_state is not None
                candidate_metadata_fingerprint = (
                    requirement_action_candidate_metadata_fingerprint(
                        source_reference_id=source_reference_id,
                        sequence=raw.candidate_sequence,
                        event_kind=event_kind,
                        tool_category=raw.candidate_tool_category,
                        occurred_at=raw.candidate_occurred_at,
                        duration_ms=raw.candidate_duration_ms,
                        family=raw.candidate_family,
                        state=raw.candidate_state,
                    )
                )
                candidate_metadata_fingerprint_version = (
                    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
                )
            tool = self._redactor.redact(raw.tool_name)
            invocation = self._redactor.redact(raw.invocation_preview)
            effect = (
                None
                if raw.result_or_effect_preview is None
                else self._redactor.redact(raw.result_or_effect_preview)
            )
            descriptors.append(
                EphemeralRedactedActionDescriptor(
                    source_reference_id=source_reference_id,
                    event_kind=event_kind,
                    tool_name=tool.text,
                    invocation_preview=invocation.text,
                    result_or_effect_preview=(
                        None if effect is None else effect.text
                    ),
                    invocation_truncated=raw.invocation_truncated,
                    result_or_effect_truncated=raw.result_or_effect_truncated,
                    redactor_version=self._redactor.version,
                    candidate_metadata_fingerprint_version=(
                        candidate_metadata_fingerprint_version
                    ),
                    candidate_metadata_fingerprint=(
                        candidate_metadata_fingerprint
                    ),
                )
            )
        return tuple(descriptors)

    @staticmethod
    def _scope_incomplete_reasons(
        *,
        thread: RawCodexTextThread,
        selection: TextAnalysisSelection,
        observed: tuple[_CandidateMessage, ...],
        eligible_count: int,
        extraction_complete: bool,
    ) -> tuple[TextAnalysisScopeReason, ...]:
        if extraction_complete:
            return ()
        reasons: list[TextAnalysisScopeReason] = []
        if thread.older_history_truncated:
            reasons.append(TextAnalysisScopeReason.SOURCE_HISTORY_LIMIT)
        if thread.unclassified_omission:
            reasons.append(TextAnalysisScopeReason.SOURCE_VARIANT_UNCLASSIFIED)
        if len(observed) < eligible_count:
            if len(observed) >= selection.max_messages:
                reasons.append(TextAnalysisScopeReason.MESSAGE_LIMIT)
            else:
                reasons.append(TextAnalysisScopeReason.CHARACTER_LIMIT)
        if not reasons:
            reasons.append(TextAnalysisScopeReason.COMPLETENESS_UNPROVEN)
        return tuple(reasons)

    def _redacted_candidates(
        self,
        thread: RawCodexTextThread,
        safe_session_id: str,
    ) -> tuple[_CandidateMessage, ...]:
        candidates: list[_CandidateMessage] = []
        final_user_item = next(
            (
                (
                    fragment.turn_id.get_secret_value(),
                    fragment.item_id.get_secret_value(),
                )
                for fragment in reversed(thread.fragments)
                if fragment.kind is CodexTextItemKind.USER_MESSAGE
            ),
            None,
        )
        observed_agent_activity = False
        for sequence, fragment in enumerate(thread.fragments):
            redacted = self._redactor.redact(fragment.text)
            language = self._language_detector.detect(redacted.text)
            raw_identity = _encode_identity(
                fragment.turn_id.get_secret_value(),
                fragment.item_id.get_secret_value(),
                str(fragment.content_index),
                str(fragment.segment_index),
                fragment.kind.value,
            )
            message_id = self._pseudonymizer.pseudonymize(
                f"codex:text-message:{safe_session_id}", raw_identity
            )
            if fragment.kind is CodexTextItemKind.USER_MESSAGE:
                role = TextRole.USER
                user_item = (
                    fragment.turn_id.get_secret_value(),
                    fragment.item_id.get_secret_value(),
                )
                kind = (
                    TextMessageKind.FEEDBACK
                    if observed_agent_activity and user_item != final_user_item
                    else TextMessageKind.REQUEST
                )
            elif fragment.kind is CodexTextItemKind.AGENT_MESSAGE:
                role = TextRole.AGENT
                kind = TextMessageKind.RESPONSE
                observed_agent_activity = True
            else:
                role = TextRole.AGENT
                kind = TextMessageKind.PLAN
                observed_agent_activity = True
            candidates.append(
                _CandidateMessage(
                    message_id=message_id,
                    sequence=sequence,
                    role=role,
                    kind=kind,
                    language=language,
                    text=redacted.text,
                )
            )
        return tuple(candidates)

    @staticmethod
    def _select_window(
        candidates: tuple[_CandidateMessage, ...],
        focus_position: int,
        selection: TextAnalysisSelection,
    ) -> tuple[tuple[_CandidateMessage, ...], bool]:
        focus = candidates[focus_position]
        used_characters = len(focus.text.get_secret_value())
        if used_characters > selection.max_characters:
            raise CodexPreviewWindowLimitError(
                "selected focus message exceeds the analysis window"
            )
        selected: set[int] = {focus_position}

        for index in range(focus_position + 1, len(candidates)):
            text_length = len(candidates[index].text.get_secret_value())
            if (
                len(selected) >= selection.max_messages
                or used_characters + text_length > selection.max_characters
            ):
                break
            selected.add(index)
            used_characters += text_length

        left_boundary_closed = False
        for index in range(focus_position - 1, -1, -1):
            text_length = len(candidates[index].text.get_secret_value())
            if (
                len(selected) >= selection.max_messages
                or used_characters + text_length > selection.max_characters
            ):
                left_boundary_closed = True
                break
            selected.add(index)
            used_characters += text_length

        left_boundary_closed = left_boundary_closed or (
            len(selected) >= selection.max_messages
            or used_characters >= selection.max_characters
        )
        return (
            tuple(candidates[index] for index in sorted(selected)),
            left_boundary_closed,
        )

"""Prompt check: validate one prompt in its context before an agent acts on it (ADR 0015).

A coding agent (or the person) sends the prompt that is about to be sent,
optionally with the earlier messages of the conversation. The app answers with

* the same deterministic prompt metrics the dashboard uses for sessions
  (coaching pack, focus request only), with the cues it detected or missed,
* content-free context inference (task type, language, dependence on earlier
  messages, references, whether verification was asked for),
* when a local model is active, commentary: findings, a reformulated prompt
  that keeps the person's intent, and element-level rewrites - marked as model
  output, never a metric,
* a compact summary the agent can show or act on.

Only metrics and content-free counters are persisted (history and plots); the
prompt text, the prior messages and the commentary are returned to the caller
and never stored.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import hmac
import secrets
import json
import re
from typing import Any, Literal, Protocol

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator

from ..domain import DataTier, PSEUDONYM_PATTERN, Provider, StrictModel
from .model_reply import completed_chat_content, model_json_object
from .analysis.coaching_baselines import DEFAULT_COACHING_METRIC_ENGINE
from .analysis.text_analysis_presets import COACHING_PROFILE_V1
from .analysis.text_baselines import TextMetricEngine
from .analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1LocalAnalysisGrant,
    P1TextAnalysisInput,
    TextAnalysisScope,
    TextAnalysisScopeKind,
    TextAnalysisScopeState,
    TextLanguage,
    TextMessageKind,
    TextMetricResult,
    TextRole,
)


PROMPT_CHECK_CONTRACT_VERSION = "prompt-check.v1"
PROMPT_CHECK_PROMPT_VERSION = "prompt-check-commentary-v2-complete-json"
MAX_PROMPT_CHARS = 20_000
MAX_CONTEXT_MESSAGES = 24
MAX_CONTEXT_MESSAGE_CHARS = 8_000
MAX_CONTEXT_TOTAL_CHARS = 40_000
MAX_COMMENTARY_INPUT_CHARS = 14_000
MAX_HISTORY_PAGE = 100
#: The prompt family of the coaching pack; the other families need agent responses (a session).
PROMPT_METRIC_KEYS: tuple[str, ...] = (
    "prompt.task_definition_coverage",
    "prompt.problem_evidence_quality",
    "prompt.context_sufficiency",
    "prompt.constraint_precision",
    "prompt.acceptance_testability",
    "prompt.deliverable_contract",
)
CUE_LABELS: Mapping[str, str] = {
    "task.action": "what to do (an action verb)",
    "task.target": "what to act on (the target)",
    "task.outcome": "the intended result",
    "problem.observed": "observed behaviour",
    "problem.expected": "expected behaviour",
    "problem.reproduction": "how to reproduce",
    "problem.environment": "environment or version",
    "context.current_state": "current state",
    "context.environment": "environment or version",
    "context.boundary": "relevant boundary (files, modules, scope)",
    "constraints.detected": "constraint clauses",
    "constraints.precise": "precise constraints (value, boundary, platform, version, prohibition)",
    "acceptance.requirements": "requirement clauses",
    "acceptance.checkable": "checkable requirements (observable check, threshold, pass condition)",
    "deliverables.detected": "deliverable clauses",
    "deliverables.detailed": "detailed deliverables (format, interface, location, audience, compatibility)",
}
_TASK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fix", re.compile(r"\b(fix|debug|resolve|repair|bug|error|crash|fail(?:s|ing|ure)?|napraw|błąd|blad|nie działa|nie dziala|crashuje)\b", re.I)),
    ("test", re.compile(r"\b(write|add|create)\s+(unit\s+|integration\s+)?tests?\b|\btest coverage\b|\bnapisz testy\b|\bdodaj testy\b", re.I)),
    ("refactor", re.compile(r"\b(refactor|clean ?up|simplify|restructure|rename|zrefaktor\w*|uprość|uprosc|przenieś|przenies)\b", re.I)),
    ("review", re.compile(r"\b(review|audit|assess|critique|check (?:this|the) (?:code|pr|diff)|zrecenzuj|przejrzyj|oceń|ocen|audyt)\b", re.I)),
    ("explain", re.compile(r"\b(explain|why does|what does|how does|describe|walk me through|wyjaśnij|wyjasnij|dlaczego|jak działa|jak dziala|opisz)\b", re.I)),
    ("plan", re.compile(r"\b(plan|design|architect|propose|outline|roadmap|zaplanuj|zaprojektuj|zaproponuj)\b", re.I)),
    ("write", re.compile(r"\b(write|draft|document|readme|docs?|changelog|napisz|udokumentuj|dokumentacj\w*)\b", re.I)),
    ("implement", re.compile(r"\b(implement|add|create|build|introduce|support|make|generate|zaimplementuj|dodaj|stwórz|stworz|zbuduj|wprowadź|wprowadz)\b", re.I)),
)
_PRIOR_CONTEXT_MARKERS = re.compile(
    r"\b(as (?:before|above|earlier|discussed|mentioned|agreed)|like (?:before|last time)|the same (?:as|way)|again|"
    r"(?:that|this|the) (?:one|file|function|bug|issue|approach|plan|error|change)|continue|go on|next step|"
    r"jak (?:wcześniej|wczesniej|poprzednio|ustaliliśmy|ustalilismy|wyżej|wyzej)|to samo|tak samo|"
    r"(?:ten|ta|to|tego|tej|tym) (?:sam|sama|samo|plik|błąd|blad|problem|plan|zmian\w*)|kontynuuj|dalej)\b",
    re.I,
)
_LEADING_PRONOUN = re.compile(r"^\s*(it|this|that|they|those|these|he|she|to|tego|tym|je|go)\b", re.I)
_VERIFICATION_MARKERS = re.compile(
    r"\b(test(?:s|ed|ing)?|verify|verif(?:y|ied|ication)|validate|check (?:that|if|whether)|make sure|run (?:the )?(?:tests|build|linter|suite)|"
    r"pytest|vitest|jest|npm test|cargo test|go test|ci passes?|green|"
    r"przetestuj|sprawdź|sprawdz|zweryfikuj|upewnij się|upewnij sie|uruchom testy|testy przechodzą|testy przechodza)\b",
    re.I,
)
_FILE_REFERENCE = re.compile(r"(?<![\w/])[\w./-]+\.(?:py|ts|tsx|js|jsx|json|md|yml|yaml|toml|rs|go|java|kt|cs|cpp|c|h|sql|css|html|sh|ps1)\b")
_CODE_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(\)|`[^`\n]{1,80}`|\b[a-z]+(?:_[a-z0-9]+){1,}\b|\b[a-z]+(?:[A-Z][a-z0-9]+){1,}\b")
_URL = re.compile(r"https?://\S+")
_SENTENCE = re.compile(r"[.!?]+(?:\s|$)")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|\[[ xX-]\])\s+", re.M)
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_COMMON_WORDS = frozenset(
    {
        "about", "after", "again", "before", "between", "could", "every", "first", "请", "should", "their", "there",
        "these", "thing", "things", "those", "through", "under", "which", "while", "would", "write", "please", "make",
        "change", "changes", "update", "implement", "create", "tests", "test", "using", "where", "other", "without",
        "także", "które", "który", "która", "proszę", "zrobić", "dodać", "zmiany", "zmianę", "przez", "jest", "oraz",
    }
)
EXPLANATION_PHRASES: Mapping[str, str] = {
    "unsupported_language": "too short or language not recognised (English and Polish are analysed)",
    "diagnostic_task_not_detected": "only measured for bug / diagnosis prompts",
    "constraints_unobserved": "no constraint clause detected",
    "requirements_unknown": "no requirement clause detected",
    "deliverables_unobserved": "no deliverable clause detected",
    "source_extraction_incomplete": "the text could not be analysed completely",
    "message_kind_unobserved": "needs a message kind this prompt does not contain",
}


class PromptCheckError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ----- request -----


class PromptCheckMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CONTEXT_MESSAGE_CHARS)


class PromptCheckRequest(StrictModel):
    """The prompt about to be sent, the earlier turns if the agent has them, and hints about the agent."""

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    prior_messages: tuple[PromptCheckMessage, ...] = Field(default=(), max_length=MAX_CONTEXT_MESSAGES)
    #: When set, the session's own redacted tail becomes the prior context (server-side, consent-gated).
    session_id: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    provider: Literal["codex", "claude_code", "other"] = "other"
    agent_model: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._:/+-]*$")
    want_commentary: bool = True
    remote_approval: str | None = Field(default=None, max_length=100, repr=False)

    @field_validator("prompt")
    @classmethod
    def prompt_has_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must contain text")
        return value

    @model_validator(mode="after")
    def bound_context(self) -> PromptCheckRequest:
        if sum(len(m.content) for m in self.prior_messages) > MAX_CONTEXT_TOTAL_CHARS:
            raise ValueError("prior messages exceed the context bound")
        return self


# ----- results -----


class PromptCue(StrictModel):
    code: str
    label: str
    status: Literal["detected", "missing", "counted", "unknown"]
    count: int | None = None


class PromptMetricReading(StrictModel):
    key: str
    display_name: str
    description: str
    state: Literal["known", "unknown", "not_applicable", "abstained", "execution_error"]
    value: float | None = None
    numerator: int | None = None
    denominator: int | None = None
    higher_is_better: bool = True
    explanation_code: str
    cues: tuple[PromptCue, ...] = ()


class ContextInference(StrictModel):
    task_type: Literal["implement", "fix", "refactor", "review", "explain", "plan", "write", "test", "other"]
    language: Literal["en", "pl", "mixed", "unknown"]
    prompt_chars: int = Field(ge=0)
    prompt_words: int = Field(ge=0)
    sentence_count: int = Field(ge=0)
    bullet_count: int = Field(ge=0)
    question_count: int = Field(ge=0)
    file_references: int = Field(ge=0)
    code_identifiers: int = Field(ge=0)
    urls: int = Field(ge=0)
    prior_context_supplied: int = Field(ge=0)
    depends_on_prior_context: bool
    verification_requested: bool
    missing_elements: tuple[str, ...] = ()


class CommentaryFinding(StrictModel):
    aspect: Literal["goal", "scope", "context", "constraints", "acceptance", "deliverable", "verification", "ambiguity", "other"]
    severity: Literal["low", "medium", "high"]
    why: str = Field(min_length=1, max_length=600)
    suggestion: str = Field(min_length=1, max_length=800)

    @field_validator("why", "suggestion")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_reply_invalid")
        return value.strip()


class ReformulatedElement(StrictModel):
    element: Literal["goal", "scope", "context", "constraints", "acceptance", "deliverable", "verification", "other"]
    original: str | None = Field(default=None, max_length=600)
    suggested: str = Field(min_length=1, max_length=1_200)

    @field_validator("suggested")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_reply_invalid")
        return value.strip()


class _CommentaryReply(StrictModel):
    findings: list[CommentaryFinding] = Field(default_factory=list, max_length=6)
    reformulated_prompt: str | None = Field(default=None, min_length=1, max_length=MAX_PROMPT_CHARS * 2 + 2_000)
    reformulated_elements: list[ReformulatedElement] = Field(default_factory=list, max_length=8)
    notes: str | None = Field(default=None, min_length=1, max_length=1_000)

    @field_validator("reformulated_prompt", "notes")
    @classmethod
    def _nonblank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("model_reply_invalid")
        return value.strip() if value is not None else None


class ModelCommentary(StrictModel):
    state: Literal["ok", "no_active_model", "model_error", "reply_invalid", "skipped"]
    model_alias: str | None = None
    prompt_version: str = PROMPT_CHECK_PROMPT_VERSION
    inference_provider: Literal["local", "litellm"] = "local"
    model_revision: str | None = None
    model_license: str | None = None
    redactor_version: str | None = None
    adapter_version: str | None = None
    findings: tuple[CommentaryFinding, ...] = ()
    reformulated_prompt: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS * 2 + 2_000)
    reformulated_elements: tuple[ReformulatedElement, ...] = ()
    notes: str | None = Field(default=None, max_length=1_000)
    caveat: str = (
        "Commentary and rewrites come from a local model; they are suggestions, not metrics, and may be wrong. "
        "The deterministic cues above are what was actually detected."
    )


class PromptCheckConfiguration(StrictModel):
    remote: bool = False
    model: str | None = None
    provider: Literal["local", "litellm"] = "local"


class PromptCheckPreview(StrictModel):
    model: str
    provider: Literal["litellm"] = "litellm"
    messages: tuple[dict[str, str], ...] = Field(repr=False)
    approval: str = Field(repr=False)
    expires_in_seconds: int = 600
    redactor_version: str
    prompt_version: str = PROMPT_CHECK_PROMPT_VERSION
    model_revision: str | None = None
    model_license: str | None = None


class PromptCheckResult(StrictModel):
    contract_version: Literal[PROMPT_CHECK_CONTRACT_VERSION] = PROMPT_CHECK_CONTRACT_VERSION
    check_id: str
    created_at: datetime
    provider: Literal["codex", "claude_code", "other"]
    agent_model: str | None = None
    metrics: tuple[PromptMetricReading, ...]
    context: ContextInference
    commentary: ModelCommentary
    summary: str
    engine_version: str
    rubric_version: str
    dashboard_path: str
    other_metric_families_note: str = (
        "Collaboration, logic and outcome metrics need the agent's replies and the session's evidence; "
        "they are computed for the session afterwards, not for a single prompt."
    )


class PromptCheckRecord(StrictModel):
    """Stored history row: metrics and counters only; no text."""

    check_id: str
    created_at: datetime
    provider: Literal["codex", "claude_code", "other"]
    agent_model: str | None = None
    language: str
    task_type: str
    prompt_chars: int = Field(ge=0)
    prior_message_count: int = Field(ge=0)
    depends_on_prior_context: bool
    verification_requested: bool
    metrics: tuple[PromptMetricReading, ...]
    commentary_state: str
    commentary_model_alias: str | None = None
    prompt_fingerprint: str


class PromptCheckHistory(StrictModel):
    contract_version: Literal[PROMPT_CHECK_CONTRACT_VERSION] = PROMPT_CHECK_CONTRACT_VERSION
    checks: tuple[PromptCheckRecord, ...]
    limit: int
    offset: int


class PromptCheckRepository(Protocol):
    def insert(self, record: PromptCheckRecord) -> None: ...

    def list(self, *, limit: int, offset: int) -> tuple[PromptCheckRecord, ...]: ...

    def get(self, check_id: str) -> PromptCheckRecord | None: ...


class Redactor(Protocol):
    version: str

    def redact(self, value: SecretStr) -> Any: ...


class LanguageDetector(Protocol):
    def detect(self, value: SecretStr) -> TextLanguage: ...


# ----- the service -----


_SYSTEM_PROMPT = (
    "You review prompts that people send to coding agents (Claude Code, Codex). You get the prompt about to be sent, "
    "optionally the earlier conversation, and deterministic findings. Answer with strict JSON only, no markdown, no code fences: "
    '{"findings":[{"aspect":"goal|scope|context|constraints|acceptance|deliverable|verification|ambiguity|other",'
    '"severity":"low|medium|high","why":"...","suggestion":"..."}],'
    '"reformulated_prompt":"...","reformulated_elements":[{"element":"goal|scope|context|constraints|acceptance|deliverable|verification|other",'
    '"original":"... or null","suggested":"..."}],"notes":"..."}. '
    "Rules: keep the person's intent, language and tone; never invent facts or values - any parameter, number, path or name the person "
    "did not state must appear as a placeholder like <specify: max retries> so the person fills it; the reformulated prompt must stay "
    "concise (at most twice the original length); "
    "at most six findings ordered by severity; if the prompt is already good say so in notes and keep findings short; "
    "if the prompt relies on the earlier conversation, say what must be restated when starting fresh."
)


class PromptCheckService:
    def __init__(
        self,
        repository: PromptCheckRepository,
        *,
        pseudonymize: Callable[[str, str], str],
        engine: TextMetricEngine = DEFAULT_COACHING_METRIC_ENGINE,
        redactor: Redactor | None = None,
        language_detector: LanguageDetector | None = None,
        chat: Callable[[str, bytes], tuple[int, bytes, str]] | None = None,
        active_model: Callable[[], str | None] | None = None,
        session_context: Callable[[str], tuple[PromptCheckMessage, ...]] | None = None,
        clock: Callable[[], datetime] | None = None,
        dashboard_path: str = "/prompt-checks",
        remote_model: str | None = None,
        remote_model_revision: str | None = None,
        remote_model_license: str | None = None,
    ) -> None:
        self._repository = repository
        self._pseudonymize = pseudonymize
        self._engine = engine
        if redactor is None:
            from ..infrastructure.redaction import DeterministicLocalRedactor

            redactor = DeterministicLocalRedactor()
        if language_detector is None:
            from ..infrastructure.language import DeterministicEnglishPolishDetector

            language_detector = DeterministicEnglishPolishDetector()
        self._redactor = redactor
        self._language = language_detector
        self._chat = chat
        self._active_model = active_model or (lambda: None)
        self._session_context = session_context
        self._clock = clock or (lambda: datetime.now(UTC))
        self._dashboard_path = dashboard_path
        self._remote_model = remote_model
        self._remote_revision = remote_model_revision
        self._remote_license = remote_model_license
        self._preview_key = secrets.token_bytes(32)

    # -- public --

    def configuration(self) -> PromptCheckConfiguration:
        return PromptCheckConfiguration(
            remote=self._remote_model is not None,
            model=self._remote_model,
            provider="litellm" if self._remote_model else "local",
        )

    def _remote_body(self, request: PromptCheckRequest) -> bytes:
        if request.session_id is not None:
            raise PromptCheckError("remote_session_context_forbidden")
        text = request.prompt.strip()
        readings = self._deterministic_readings("0" * 64, text, request.prior_messages)
        context = self._infer_context(text, request.prior_messages, readings)
        return self._commentary_body(request, text, readings, context)

    def _approval(self, body: bytes, issued: int) -> str:
        payload = str(issued).encode() + b"\0" + (self._remote_model or "").encode() + b"\0" + body
        return f"{issued}." + hmac.new(self._preview_key, payload, hashlib.sha256).hexdigest()

    def preview(self, request: PromptCheckRequest) -> PromptCheckPreview:
        if self._remote_model is None:
            raise PromptCheckError("remote_model_not_configured")
        body = self._remote_body(request)
        issued = int(self._clock().timestamp())
        return PromptCheckPreview(
            model=self._remote_model,
            messages=tuple(json.loads(body)["messages"]),
            approval=self._approval(body, issued),
            redactor_version=self._redactor.version,
            model_revision=self._remote_revision,
            model_license=self._remote_license,
        )

    def _require_remote_approval(self, request: PromptCheckRequest) -> None:
        body = self._remote_body(request)
        token = request.remote_approval or ""
        try:
            issued = int(token.split(".", 1)[0])
        except ValueError:
            raise PromptCheckError("remote_preview_required") from None
        age = int(self._clock().timestamp()) - issued
        if not 0 <= age <= 600 or not hmac.compare_digest(token, self._approval(body, issued)):
            raise PromptCheckError("remote_preview_required")

    def check(self, request: PromptCheckRequest) -> PromptCheckResult:
        if self._remote_model is not None and request.want_commentary:
            self._require_remote_approval(request)
        created_at = self._clock()
        if request.session_id and not request.prior_messages and self._session_context is not None:
            try:
                context_messages = self._session_context(request.session_id)[-MAX_CONTEXT_MESSAGES:]
            except Exception:
                context_messages = ()
            if context_messages:
                request = request.model_copy(update={"prior_messages": context_messages})
        prompt_text = request.prompt.strip()
        check_id = hashlib.sha256(
            f"{created_at.isoformat()}|{len(prompt_text)}|{hashlib.sha256(prompt_text.encode('utf-8')).hexdigest()}".encode("utf-8")
        ).hexdigest()
        readings = self._deterministic_readings(check_id, prompt_text, request.prior_messages)
        context = self._infer_context(prompt_text, request.prior_messages, readings)
        commentary = self._commentary(request, prompt_text, readings, context)
        if self._remote_model is not None:
            commentary = commentary.model_copy(update={
                "caveat": "Commentary and rewrites come from the configured LiteLLM model; "
                "they are suggestions, not metrics, and may be wrong.",
                "inference_provider": "litellm",
                "model_revision": self._remote_revision,
                "model_license": self._remote_license,
                "redactor_version": self._redactor.version,
                "adapter_version": "litellm-chat-v1",
            })
        summary = _summary(readings, context, commentary)
        result = PromptCheckResult(
            check_id=check_id,
            created_at=created_at,
            provider=request.provider,
            agent_model=request.agent_model,
            metrics=readings,
            context=context,
            commentary=commentary,
            summary=summary,
            engine_version=self._engine.engine_version,
            rubric_version=self._engine.rubric_version,
            dashboard_path=f"{self._dashboard_path}/{check_id}",
        )
        self._repository.insert(
            PromptCheckRecord(
                check_id=check_id,
                created_at=created_at,
                provider=request.provider,
                agent_model=request.agent_model,
                language=context.language,
                task_type=context.task_type,
                prompt_chars=context.prompt_chars,
                prior_message_count=len(request.prior_messages),
                depends_on_prior_context=context.depends_on_prior_context,
                verification_requested=context.verification_requested,
                metrics=readings,
                commentary_state=commentary.state,
                commentary_model_alias=commentary.model_alias,
                prompt_fingerprint=self._pseudonymize("prompt-check:text", prompt_text),
            )
        )
        return result

    def history(self, *, limit: int = 50, offset: int = 0) -> PromptCheckHistory:
        limit = max(1, min(limit, MAX_HISTORY_PAGE))
        return PromptCheckHistory(checks=self._repository.list(limit=limit, offset=max(0, offset)), limit=limit, offset=max(0, offset))

    def get(self, check_id: str) -> PromptCheckRecord:
        if PSEUDONYM_PATTERN.fullmatch(check_id) is None:
            raise PromptCheckError("check_not_found")
        record = self._repository.get(check_id)
        if record is None:
            raise PromptCheckError("check_not_found")
        return record

    # -- deterministic metrics through the coaching engine --

    def _deterministic_readings(
        self, check_id: str, prompt_text: str, prior: tuple[PromptCheckMessage, ...]
    ) -> tuple[PromptMetricReading, ...]:
        session_id = self._pseudonymize("prompt-check:session", check_id)
        messages: list[EphemeralRedactedMessage] = []
        sequence = 0
        saw_agent = False
        for item in prior:
            redacted = self._redactor.redact(SecretStr(item.content))
            text = redacted.text if isinstance(redacted.text, SecretStr) else SecretStr(str(redacted.text))
            if item.role == "assistant":
                role, kind, saw_agent = TextRole.AGENT, TextMessageKind.RESPONSE, True
            else:
                role, kind = TextRole.USER, (TextMessageKind.FEEDBACK if saw_agent else TextMessageKind.REQUEST)
            messages.append(
                EphemeralRedactedMessage(
                    message_id=self._pseudonymize("prompt-check:message", f"{check_id}:{sequence}"),
                    sequence=sequence,
                    role=role,
                    kind=kind,
                    language=self._language.detect(text),
                    text=text,
                )
            )
            sequence += 1
        focus_redacted = self._redactor.redact(SecretStr(prompt_text))
        focus_text = focus_redacted.text if isinstance(focus_redacted.text, SecretStr) else SecretStr(str(focus_redacted.text))
        focus_id = self._pseudonymize("prompt-check:message", f"{check_id}:{sequence}")
        messages.append(
            EphemeralRedactedMessage(
                message_id=focus_id,
                sequence=sequence,
                role=TextRole.USER,
                kind=TextMessageKind.REQUEST,
                language=self._language.detect(focus_text),
                text=focus_text,
            )
        )
        available = frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK, TextMessageKind.RESPONSE})
        total_chars = sum(len(m.text.get_secret_value()) for m in messages)
        scope = TextAnalysisScope(
            kind=TextAnalysisScopeKind.FULL_AVAILABLE_SESSION,
            state=TextAnalysisScopeState.COMPLETE,
            requested_max_messages=max(1, len(messages)),
            requested_max_characters=max(1, min(total_chars, 100_000)),
            source_history_complete=True,
        )
        fingerprint = self._pseudonymize("prompt-check:window", f"{check_id}:{total_chars}:{len(messages)}")
        context = P1TextAnalysisInput(
            provider=Provider.SYNTHETIC,
            session_id=session_id,
            provider_version="prompt-check-1",
            adapter_version="prompt-check-adapter-1",
            source_schema_version="prompt-check-source-1",
            content_schema_version="prompt-check-content-1",
            redactor_version=self._redactor.version,
            analysis_scope=scope,
            text_extraction_complete=True,
            available_message_kinds=available,
            analysis_window_fingerprint=fingerprint,
            focus_message_id=focus_id,
            observed_message_count=len(messages),
            eligible_message_count=len(messages),
            messages=tuple(messages),
            task_profile=COACHING_PROFILE_V1.task_profile,
        )
        grant = P1LocalAnalysisGrant(
            provider=Provider.SYNTHETIC,
            session_id=session_id,
            analysis_window_fingerprint=fingerprint,
            data_tier=DataTier.REDACTED_CONTENT,
            consent_active=True,
            local_only=True,
            content_persistence_allowed=False,
        )
        results = self._engine.compute(
            context, grant, pack_key=self._engine.pack_key, pack_version=self._engine.pack_version
        )
        by_key = {result.observation.key: result for result in results}
        return tuple(_reading(by_key[key]) for key in PROMPT_METRIC_KEYS if key in by_key)

    # -- context inference (content-free outputs) --

    def _infer_context(
        self, prompt_text: str, prior: tuple[PromptCheckMessage, ...], readings: tuple[PromptMetricReading, ...]
    ) -> ContextInference:
        language = self._language.detect(SecretStr(prompt_text))
        # Earliest-mentioned task verb wins; the pattern order only breaks ties.
        task_type: str = "other"
        best: tuple[int, int] | None = None
        for order, (name, pattern) in enumerate(_TASK_PATTERNS):
            match = pattern.search(prompt_text)
            if match and (best is None or (match.start(), order) < best):
                best = (match.start(), order)
                task_type = name
        words = len(prompt_text.split())
        depends = bool(_PRIOR_CONTEXT_MARKERS.search(prompt_text)) or bool(_LEADING_PRONOUN.match(prompt_text)) or (
            words <= 6 and not _FILE_REFERENCE.search(prompt_text)
        )
        if not depends and prior and not _FILE_REFERENCE.search(prompt_text):
            # The prompt names things only the earlier turns identify (shared rare words, no explicit file).
            prompt_tokens = {t for t in _WORD.findall(prompt_text.casefold()) if len(t) >= 5 and t not in _COMMON_WORDS}
            prior_tokens = {t for m in prior for t in _WORD.findall(m.content.casefold()) if len(t) >= 5}
            depends = len(prompt_tokens & prior_tokens) >= 2
        missing: list[str] = []
        for reading in readings:
            if reading.state != "known":
                continue
            for cue in reading.cues:
                if cue.status == "missing" and cue.label not in missing:
                    missing.append(cue.label)
            if reading.key == "prompt.constraint_precision" and reading.denominator == 0 and "constraints" not in " ".join(missing):
                pass
        by_key = {reading.key: reading for reading in readings}
        constraints = by_key.get("prompt.constraint_precision")
        if constraints is not None and constraints.state != "known":
            missing.append("any constraint (what must not change, limits, platform)")
        acceptance = by_key.get("prompt.acceptance_testability")
        if acceptance is not None and acceptance.state != "known":
            missing.append("an acceptance criterion (how you will know it is done)")
        deliverable = by_key.get("prompt.deliverable_contract")
        if deliverable is not None and deliverable.state != "known":
            missing.append("the deliverable (what should exist at the end, where, in what form)")
        verification = bool(_VERIFICATION_MARKERS.search(prompt_text))
        if not verification:
            missing.append("how the result should be verified (tests, build, inspection)")
        return ContextInference(
            task_type=task_type,  # type: ignore[arg-type]
            language=language.value,  # type: ignore[arg-type]
            prompt_chars=len(prompt_text),
            prompt_words=words,
            sentence_count=max(1, len(_SENTENCE.findall(prompt_text))) if prompt_text.strip() else 0,
            bullet_count=len(_BULLET.findall(prompt_text)),
            question_count=prompt_text.count("?"),
            file_references=len(_FILE_REFERENCE.findall(prompt_text)),
            code_identifiers=len(_CODE_IDENTIFIER.findall(prompt_text)),
            urls=len(_URL.findall(prompt_text)),
            prior_context_supplied=len(prior),
            depends_on_prior_context=depends,
            verification_requested=verification,
            missing_elements=tuple(missing[:8]),
        )

    # -- model commentary --

    def _commentary(
        self,
        request: PromptCheckRequest,
        prompt_text: str,
        readings: tuple[PromptMetricReading, ...],
        context: ContextInference,
    ) -> ModelCommentary:
        if not request.want_commentary:
            return ModelCommentary(state="skipped")
        alias = self._active_model()
        if alias is None or self._chat is None:
            return ModelCommentary(state="no_active_model")
        body = self._commentary_body(request, prompt_text, readings, context)
        try:
            status, payload, _ = self._chat(alias, body)
        except Exception:
            return ModelCommentary(state="model_error", model_alias=alias)
        if status != 200:
            return ModelCommentary(state="model_error", model_alias=alias)
        text = completed_chat_content(payload)
        parsed = parse_commentary_reply(text, prompt_chars=len(prompt_text))
        if parsed is None:
            return ModelCommentary(state="reply_invalid", model_alias=alias)
        return parsed.model_copy(update={"model_alias": alias})

    def _commentary_body(
        self, request: PromptCheckRequest, prompt_text: str,
        readings: tuple[PromptMetricReading, ...], context: ContextInference,
    ) -> bytes:
        user_message = _commentary_input(request, prompt_text, readings, context)
        if self._remote_model is not None:
            from ..infrastructure.redaction import LocalRedactionError
            try:
                user_message = self._redactor.redact(SecretStr(user_message)).text.get_secret_value()
            except LocalRedactionError:
                raise PromptCheckError("remote_redaction_failed") from None
        payload = {
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.2,
            "max_tokens": 1_100,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if self._remote_model is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "prompt_commentary", "schema": _CommentaryReply.model_json_schema()},
            }
        return json.dumps(payload).encode("utf-8")


# ----- helpers -----


def _reading(result: TextMetricResult) -> PromptMetricReading:
    fraction = result.fraction
    value = result.observation.numeric_value
    definition_name = getattr(result.observation, "display_name", None)
    description = ""
    display_name = definition_name or result.observation.key
    from .analysis.coaching_baselines import COACHING_METRIC_DEFINITIONS

    for definition in COACHING_METRIC_DEFINITIONS:
        if definition.key == result.observation.key:
            display_name, description = definition.display_name, definition.description
            break
    cues = tuple(
        PromptCue(
            code=signal.code,
            label=CUE_LABELS.get(signal.code, signal.code.replace(".", " ").replace("_", " ")),
            status=signal.status.value,  # type: ignore[arg-type]
            count=signal.count,
        )
        for signal in result.signals
    )
    return PromptMetricReading(
        key=result.observation.key,
        display_name=display_name,
        description=description,
        state=result.value_state.value,  # type: ignore[arg-type]
        value=value,
        numerator=fraction.numerator if fraction else None,
        denominator=fraction.denominator if fraction else None,
        higher_is_better=result.direction.value != "lower_is_better",
        explanation_code=result.explanation_code,
        cues=cues,
    )


def _commentary_input(
    request: PromptCheckRequest,
    prompt_text: str,
    readings: tuple[PromptMetricReading, ...],
    context: ContextInference,
) -> str:
    budget = MAX_COMMENTARY_INPUT_CHARS - min(len(prompt_text), MAX_COMMENTARY_INPUT_CHARS // 2)
    prior_lines: list[str] = []
    used = 0
    for item in reversed(request.prior_messages):
        snippet = item.content.strip()
        if len(snippet) > 1_500:
            snippet = snippet[:1_500] + " …"
        if used + len(snippet) > budget:
            break
        prior_lines.append(f"{item.role}: {snippet}")
        used += len(snippet)
    prior_lines.reverse()
    findings = []
    for reading in readings:
        if reading.state == "known":
            missing = [cue.label for cue in reading.cues if cue.status == "missing"]
            findings.append(f"- {reading.display_name}: {reading.numerator}/{reading.denominator}" + (f" (missing: {', '.join(missing)})" if missing else ""))
        else:
            findings.append(f"- {reading.display_name}: {reading.state} ({reading.explanation_code})")
    parts = []
    if prior_lines:
        parts.append("Earlier conversation (most recent last):\n" + "\n".join(prior_lines))
    else:
        parts.append("Earlier conversation: none supplied.")
    parts.append("Prompt to review:\n" + prompt_text[: MAX_COMMENTARY_INPUT_CHARS // 2])
    parts.append(
        "Deterministic findings:\n" + "\n".join(findings)
        + f"\n- task type guess: {context.task_type}; language: {context.language}; "
        + f"depends on earlier conversation: {'yes' if context.depends_on_prior_context else 'no'}; "
        + f"verification requested: {'yes' if context.verification_requested else 'no'}"
    )
    return "\n\n".join(parts)


def parse_commentary_reply(text: object, *, prompt_chars: int) -> ModelCommentary | None:
    """Reject malformed suggestions; never manufacture labels, reasons or text."""

    data = model_json_object(text)
    if data is None or type(prompt_chars) is not int or prompt_chars < 0:
        return None
    try:
        reply = _CommentaryReply.model_validate(data, strict=True)
    except ValidationError:
        return None
    if reply.reformulated_prompt is not None and len(reply.reformulated_prompt) > max(prompt_chars * 2 + 2_000, 200):
        return None
    if not (reply.findings or reply.reformulated_prompt or reply.reformulated_elements or reply.notes):
        return None
    return ModelCommentary(
        state="ok",
        findings=tuple(sorted(reply.findings, key=lambda finding: _SEVERITY_ORDER[finding.severity])),
        reformulated_prompt=reply.reformulated_prompt,
        reformulated_elements=tuple(reply.reformulated_elements),
        notes=reply.notes,
    )


def _summary(readings: tuple[PromptMetricReading, ...], context: ContextInference, commentary: ModelCommentary) -> str:
    parts: list[str] = []
    known = [r for r in readings if r.state == "known"]
    for reading in known:
        missing = [cue.label for cue in reading.cues if cue.status == "missing"]
        piece = f"{reading.display_name}: {reading.numerator}/{reading.denominator}"
        if missing:
            piece += " (missing: " + ", ".join(missing) + ")"
        parts.append(piece)
    unknown = [
        f"{r.display_name} ({EXPLANATION_PHRASES.get(r.explanation_code, r.explanation_code.replace('_', ' '))})"
        for r in readings
        if r.state != "known"
    ]
    if unknown:
        parts.append("not measurable on this prompt: " + "; ".join(unknown))
    parts.append(f"task type: {context.task_type}; language: {context.language}; {context.prompt_words} words")
    parts.append(
        "depends on earlier conversation: "
        + ("yes" if context.depends_on_prior_context else "no")
        + (f" ({context.prior_context_supplied} earlier messages supplied)" if context.prior_context_supplied else " (no earlier messages supplied)")
    )
    parts.append("verification requested: " + ("yes" if context.verification_requested else "no"))
    if context.missing_elements:
        parts.append("consider adding: " + "; ".join(context.missing_elements))
    if commentary.state == "ok":
        top = [f"[{f.severity}] {f.suggestion}" for f in commentary.findings[:3]]
        if top:
            parts.append("model suggestions: " + " | ".join(top))
        if commentary.reformulated_prompt:
            parts.append("a reformulated prompt is included (model output; keep what matches your intent)")
    elif commentary.state == "no_active_model":
        parts.append("no local model active: deterministic cues only (activate one on the Models page for commentary)")
    return "Prompt check - " + ". ".join(parts) + "."


__all__ = (
    "CUE_LABELS",
    "EXPLANATION_PHRASES",
    "MAX_CONTEXT_MESSAGES",
    "MAX_PROMPT_CHARS",
    "PROMPT_CHECK_CONTRACT_VERSION",
    "PROMPT_CHECK_PROMPT_VERSION",
    "PROMPT_METRIC_KEYS",
    "CommentaryFinding",
    "ContextInference",
    "ModelCommentary",
    "PromptCheckError",
    "PromptCheckHistory",
    "PromptCheckMessage",
    "PromptCheckRecord",
    "PromptCheckRepository",
    "PromptCheckRequest",
    "PromptCheckResult",
    "PromptCheckService",
    "PromptCue",
    "PromptMetricReading",
    "ReformulatedElement",
    "parse_commentary_reply",
)

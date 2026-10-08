"""Automatic acceptance of single-session task candidates.

The owner's direction (2026-08-19): propose-then-accept stays the rule for
anything a person should look at - merges, splits, multi-session groupings -
but a candidate that is exactly one session carries no grouping judgement to
review.  Accepting it automatically gives the evidence metrics the reviewed
denominator ADR 0012 requires (one current accepted revision per session)
without a click, and the decision is recorded with ``decision_source =
"automation"`` so it is never mistaken for a person's review.  Task category
stays ``UNKNOWN``: automation does not guess what kind of work it was.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ...domain import Provider
from ..persistence import CandidateDecisionStatus
from .contracts import AcceptCandidate, TaskCategory
from .review import TaskReviewService


AUTO_ACCEPT_SOURCE = "automation"
AUTO_ACCEPT_IDEMPOTENCY_PREFIX = "auto-accept-singleton-"
MAX_AUTO_ACCEPT_PER_PASS = 500


@dataclass(frozen=True, slots=True)
class AutoAcceptResult:
    examined: int
    accepted: int
    skipped_multi_session: int
    failed: int


class SingletonCandidateAutoAccepter:
    def __init__(
        self,
        repository,
        review: TaskReviewService,
        *,
        page_size: int = 100,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._repository = repository
        self._review = review
        self._page_size = max(1, min(int(page_size), 100))
        self._on_error = on_error

    def run(self, *, provider: Provider | None = None, limit: int = MAX_AUTO_ACCEPT_PER_PASS) -> AutoAcceptResult:
        """Accept undecided single-session candidates (optionally one provider)."""

        examined = accepted = skipped = failed = 0
        seen: set[str] = set()
        # Rows that stay undecided (other provider, grouped, failed) keep
        # their place in the undecided view, so the offset advances only past
        # them; accepted rows leave the view and shift the page by themselves.
        offset = 0
        bounded = max(1, min(int(limit), MAX_AUTO_ACCEPT_PER_PASS))
        while accepted + failed < bounded:
            page = self._repository.list_candidates(
                status=CandidateDecisionStatus.UNDECIDED,
                limit=self._page_size,
                offset=offset,
            )
            fresh = [item for item in page if item.candidate.candidate_id not in seen]
            if not fresh:
                break
            for item in fresh:
                candidate = item.candidate
                seen.add(candidate.candidate_id)
                if provider is not None and candidate.provider is not provider:
                    offset += 1
                    continue
                examined += 1
                if len(candidate.session_ids) != 1:
                    skipped += 1
                    offset += 1
                    continue
                try:
                    self._review.apply(
                        AcceptCandidate(
                            candidate_id=candidate.candidate_id,
                            expected_discovery_version=candidate.discovery_version,
                            task_category=TaskCategory.UNKNOWN,
                        ),
                        idempotency_key=AUTO_ACCEPT_IDEMPOTENCY_PREFIX + candidate.candidate_id[:48],
                        decision_source=AUTO_ACCEPT_SOURCE,
                    )
                    accepted += 1
                except Exception as error:  # noqa: BLE001 - one bad candidate never stops the pass
                    failed += 1
                    offset += 1
                    if self._on_error is not None:
                        self._on_error(error)
                if accepted + failed >= bounded:
                    break
        return AutoAcceptResult(examined=examined, accepted=accepted, skipped_multi_session=skipped, failed=failed)


__all__ = (
    "AUTO_ACCEPT_IDEMPOTENCY_PREFIX",
    "AUTO_ACCEPT_SOURCE",
    "AutoAcceptResult",
    "MAX_AUTO_ACCEPT_PER_PASS",
    "SingletonCandidateAutoAccepter",
)

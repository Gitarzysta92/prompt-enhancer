"""Installation-local identifiers for immutable local artifacts.

Normal identity methods accept only pseudonyms and short safe codes. The one
explicit secret-fingerprint method accepts ``SecretStr`` for privacy-reviewed,
local-only derived receipts; it never returns or persists the source value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from pydantic import SecretStr

from ..application.discovery import CandidateIdentity
from ..domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider
from ..privacy import Pseudonymizer


def _canonical(parts: tuple[str, ...]) -> str:
    if not parts or any(not SAFE_VERSION_PATTERN.fullmatch(part) for part in parts):
        raise ValueError("artifact identity accepts only short content-free values")
    return json.dumps(parts, ensure_ascii=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class LocalArtifactIdFactory:
    """Create stable, domain-separated HMAC identifiers for local artifacts."""

    pseudonymizer: Pseudonymizer = field(repr=False)

    def create(self, identity: CandidateIdentity) -> str:
        """Implement the task-discovery ``CandidateIdFactory`` port."""

        payload = _canonical(
            (
                identity.discovery_version,
                identity.provider.value,
                identity.installation_id,
                identity.project_id,
                *identity.session_ids,
            )
        )
        return self.pseudonymizer.pseudonymize("task-candidate/v1", payload)

    def decision_id(self, idempotency_key: str) -> str:
        """Map a caller retry key to an installation-local decision ID."""

        return self.pseudonymizer.pseudonymize(
            "task-decision/v1", _canonical((idempotency_key,))
        )

    def task_id(self, decision_id: str, output_ordinal: int) -> str:
        """Derive a stable output task ID without exposing the retry key."""

        if not PSEUDONYM_PATTERN.fullmatch(decision_id):
            raise ValueError("decision identifier must be a safe pseudonym")
        if output_ordinal < 0:
            raise ValueError("task output ordinal cannot be negative")
        return self.pseudonymizer.pseudonymize(
            "task/v1",
            _canonical((decision_id, str(output_ordinal))),
        )

    def analysis_run_id(
        self,
        idempotency_key: str,
        task_id: str,
        task_revision: int,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> str:
        """Derive a retry-stable ID for one task-analysis command."""

        if not SAFE_VERSION_PATTERN.fullmatch(idempotency_key):
            raise ValueError("analysis idempotency key must be a safe identifier")
        if not PSEUDONYM_PATTERN.fullmatch(task_id):
            raise ValueError("task identifier must be a safe pseudonym")
        if task_revision < 1 or metric_pack_version < 1:
            raise ValueError("analysis revisions and versions must be positive")
        if not SAFE_VERSION_PATTERN.fullmatch(metric_pack_key):
            raise ValueError("metric pack key must be a safe identifier")
        return self.pseudonymizer.pseudonymize(
            "task-analysis-run/v1",
            _canonical(
                (
                    idempotency_key,
                    task_id,
                    str(task_revision),
                    metric_pack_key,
                    str(metric_pack_version),
                )
            ),
        )

    def session_analysis_run_id(
        self,
        idempotency_key: str,
        provider: Provider,
        session_id: str,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> str:
        """Derive the shared retry-stable selected-session analysis run ID.

        This is the single keyed issuance boundary used both by the analysis
        command and by prospective comparison preparation. Keeping it on the
        installation-local factory prevents an unkeyed caller digest from
        becoming run authority.
        """

        if not SAFE_VERSION_PATTERN.fullmatch(idempotency_key):
            raise ValueError("analysis idempotency key must be a safe identifier")
        if not isinstance(provider, Provider):
            raise ValueError("analysis provider must be a known provider")
        if not PSEUDONYM_PATTERN.fullmatch(session_id):
            raise ValueError("session identifier must be a safe pseudonym")
        if not SAFE_VERSION_PATTERN.fullmatch(metric_pack_key):
            raise ValueError("metric pack key must be a safe identifier")
        if (
            not isinstance(metric_pack_version, int)
            or isinstance(metric_pack_version, bool)
            or metric_pack_version < 1
        ):
            raise ValueError("metric pack version must be positive")
        return self.fingerprint(
            "session-analysis-run-v1",
            (
                idempotency_key,
                provider.value,
                session_id,
                metric_pack_key,
                str(metric_pack_version),
            ),
        )

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        """Create a keyed fingerprint from content-free codes and pseudonyms."""

        if not SAFE_VERSION_PATTERN.fullmatch(namespace):
            raise ValueError("fingerprint namespace must be a safe identifier")
        return self.pseudonymizer.pseudonymize(
            f"artifact-fingerprint/{namespace}", _canonical(values)
        )

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        """Create a keyed digest from transient secret content and safe metadata.

        This separate method makes the secret-bearing boundary explicit. Only
        the installation-local HMAC pseudonym may leave the method.
        """

        if not SAFE_VERSION_PATTERN.fullmatch(namespace):
            raise ValueError("fingerprint namespace must be a safe identifier")
        if not isinstance(secret, SecretStr):
            raise TypeError("secret fingerprinting accepts SecretStr input only")
        raw = secret.get_secret_value()
        if not raw or "\x00" in raw:
            raise ValueError("secret fingerprint source is invalid")
        payload = _canonical(values) + "\x00" + raw
        return self.pseudonymizer.pseudonymize(
            f"artifact-secret-fingerprint/{namespace}", payload
        )

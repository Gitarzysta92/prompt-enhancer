"""Conservative, offline command-signature classifier.

This module never executes a command, reads the filesystem, resolves PATH, or
uses command output.  A match is a candidate for later provider integration,
not a live task-outcome claim.  Unknown and compound shell shapes abstain.
"""

from __future__ import annotations

import re
import shlex

from ...application.verification import (
    EphemeralVerificationCandidate,
    VerificationAbstentionReason,
    VerificationCapability,
    VerificationCapabilityState,
    VerificationClassification,
    VerificationClassificationDecision,
    VerificationKind,
)


CLASSIFIER_VERSION = "local-command-rules-v1"
NORMALIZER_VERSION = "strict-shell-free-v2"
CANDIDATE_SCHEMA_VERSION = "ephemeral-command-v1"

_SHELL_CONTROL = re.compile(r"&&|\|\||[;&|<>`^\r\n]|\$\(|\$\{")
_SHELL_EXPANSION = re.compile(
    r"\$[A-Za-z0-9_?@*#-]|%[A-Za-z_][A-Za-z0-9_]*%|![A-Za-z_][A-Za-z0-9_]*!"
)
_DISALLOWED_MODES = frozenset(
    {
        "--collect-only",
        "--co",
        "--dry-run",
        "--fix",
        "--fix-dry-run",
        "--fixtures",
        "--fixtures-per-test",
        "--help",
        "--list",
        "--list-extensions",
        "--list-groups",
        "--list-msgs",
        "--list-msgs-enabled",
        "--list-tests",
        "--listtests",
        "--markers",
        "--createstub",
        "--generate-rcfile",
        "--install-types",
        "--print-config",
        "--show-only",
        "--showconfig",
        "--update",
        "--update-snapshots",
        "--version",
        "--watch",
        "--watchall",
        "--write",
        "/?",
        "/help",
        "/version",
        "-h",
    }
)
_KNOWN_NON_VERIFICATION_EXECUTABLES = frozenset(
    {
        "cat",
        "dir",
        "echo",
        "find",
        "get-content",
        "git",
        "grep",
        "head",
        "less",
        "ls",
        "more",
        "printf",
        "rg",
        "sed",
        "tail",
        "type",
        "where",
        "which",
    }
)
_DIRECT_TESTS = frozenset({"ctest", "jest", "pytest", "py.test"})
_DIRECT_LINTERS = frozenset(
    {"eslint", "flake8", "pylint", "shellcheck", "stylelint"}
)
_DIRECT_TYPE_CHECKERS = frozenset({"mypy", "pyright"})
_DIRECT_SECURITY = frozenset({"bandit", "govulncheck", "pip-audit"})
_DIRECT_ARTIFACT_VALIDATORS = frozenset({"kubeconform", "kubeval"})


def _result(
    decision: VerificationClassificationDecision,
    *,
    kind: VerificationKind | None = None,
    rule_id: str | None = None,
    reason: VerificationAbstentionReason | None = None,
) -> VerificationClassification:
    return VerificationClassification(
        decision=decision,
        kind=kind,
        rule_id=rule_id,
        abstention_reason=reason,
        classifier_version=CLASSIFIER_VERSION,
        normalizer_version=NORMALIZER_VERSION,
    )


def _matched(kind: VerificationKind, rule_id: str) -> VerificationClassification:
    return _result(
        VerificationClassificationDecision.VERIFICATION,
        kind=kind,
        rule_id=rule_id,
    )


def _known_non_verification(rule_id: str) -> VerificationClassification:
    return _result(
        VerificationClassificationDecision.KNOWN_NON_VERIFICATION,
        rule_id=rule_id,
    )


def _abstain(reason: VerificationAbstentionReason) -> VerificationClassification:
    return _result(VerificationClassificationDecision.ABSTAINED, reason=reason)


def _normalize_executable(token: str) -> str | None:
    if not token or "/" in token or "\\" in token:
        return None
    normalized = token.casefold()
    for suffix in (".exe", ".cmd", ".bat"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized or None


def _tokenize(command: str) -> tuple[str, ...] | None:
    if (
        _SHELL_CONTROL.search(command) is not None
        or _SHELL_EXPANSION.search(command) is not None
    ):
        return None
    try:
        tokens = tuple(shlex.split(command, posix=True))
    except ValueError:
        return None
    if not tokens or len(tokens) > 256 or any(len(token) > 1_024 for token in tokens):
        return None
    return tokens


def _contains_disallowed_mode(arguments: tuple[str, ...]) -> bool:
    lowered = {
        argument.casefold().split("=", maxsplit=1)[0] for argument in arguments
    }
    return bool(lowered & _DISALLOWED_MODES)


def _contains_argument_indirection(arguments: tuple[str, ...]) -> bool:
    return any(
        argument.startswith("@") or "*" in argument or "?" in argument
        for argument in arguments
    )


class DeterministicCommandVerificationClassifier:
    """Strict full-signature rules with explicit abstention."""

    classifier_version = CLASSIFIER_VERSION
    normalizer_version = NORMALIZER_VERSION

    def classify(
        self, candidate: EphemeralVerificationCandidate
    ) -> VerificationClassification:
        if candidate.candidate_schema_version != CANDIDATE_SCHEMA_VERSION:
            return _abstain(VerificationAbstentionReason.INCOMPATIBLE_SCHEMA)
        command = candidate.command.get_secret_value()
        if not command.strip():
            return _abstain(VerificationAbstentionReason.EMPTY)
        if len(command) > 4_096:
            return _abstain(VerificationAbstentionReason.TOO_LARGE)
        tokens = _tokenize(command)
        if tokens is None:
            return _abstain(VerificationAbstentionReason.AMBIGUOUS_SHELL)
        executable = _normalize_executable(tokens[0])
        if executable is None:
            return _abstain(VerificationAbstentionReason.UNSAFE_SHAPE)
        arguments = tokens[1:]
        lowered = tuple(argument.casefold() for argument in arguments)
        if _contains_disallowed_mode(arguments) or _contains_argument_indirection(arguments):
            return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

        if executable in _KNOWN_NON_VERIFICATION_EXECUTABLES:
            return _known_non_verification("nonverification.read_or_inspect")
        if executable in {"pip", "pip3"}:
            return _known_non_verification("nonverification.package_management")
        if executable in {"npm", "pnpm", "yarn", "bun"}:
            return self._classify_package_tool(executable, lowered)
        if executable in {"python", "python3", "py"}:
            return self._classify_python_module(lowered)

        if executable in _DIRECT_TESTS:
            if executable == "ctest" and not ({"-n", "--show-only"} & set(lowered)):
                return _matched(VerificationKind.TEST, "test.ctest")
            if executable in {"pytest", "py.test", "jest"}:
                return _matched(VerificationKind.TEST, f"test.{executable.replace('.', '_')}")
        if executable == "vitest" and lowered[:1] == ("run",):
            return _matched(VerificationKind.TEST, "test.vitest_run")
        if executable == "cargo":
            return self._classify_cargo(lowered)
        if executable == "go":
            return self._classify_go(lowered)
        if executable == "dotnet":
            return self._classify_dotnet(lowered)
        if executable in {"mvn", "mvnw"}:
            return self._classify_maven(lowered)
        if executable in {"gradle", "gradlew"}:
            return self._classify_gradle(lowered)

        if executable in _DIRECT_LINTERS:
            return _matched(VerificationKind.LINT, f"lint.{executable}")
        if executable == "ruff" and lowered[:1] == ("check",):
            return _matched(VerificationKind.LINT, "lint.ruff_check")
        if executable == "golangci-lint" and lowered[:1] == ("run",):
            return _matched(VerificationKind.LINT, "lint.golangci_run")

        if executable in _DIRECT_TYPE_CHECKERS:
            return _matched(VerificationKind.TYPE_CHECK, f"type_check.{executable}")
        if executable == "pyre" and lowered[:1] == ("check",):
            return _matched(VerificationKind.TYPE_CHECK, "type_check.pyre_check")
        if executable == "tsc" and "--noemit" in lowered:
            return _matched(VerificationKind.TYPE_CHECK, "type_check.tsc_noemit")

        if executable in _DIRECT_SECURITY:
            return _matched(VerificationKind.SECURITY, f"security.{executable.replace('-', '_')}")
        if (
            executable == "semgrep"
            and lowered[:1] == ("scan",)
            and "--validate" not in lowered
        ):
            return _matched(VerificationKind.SECURITY, "security.semgrep_scan")
        if executable == "trivy" and lowered[:1] in {
            ("config",),
            ("filesystem",),
            ("fs",),
            ("image",),
            ("repo",),
        }:
            return _matched(VerificationKind.SECURITY, "security.trivy_scan")
        if executable == "gitleaks" and lowered[:1] == ("detect",):
            return _matched(VerificationKind.SECURITY, "security.gitleaks_detect")
        if executable == "safety" and lowered[:1] in {("scan",), ("check",)}:
            return _matched(VerificationKind.SECURITY, "security.safety_scan")
        if executable == "kics" and lowered[:1] == ("scan",):
            return _matched(VerificationKind.SECURITY, "security.kics_scan")

        if executable in _DIRECT_ARTIFACT_VALIDATORS:
            return _matched(
                VerificationKind.ARTIFACT_VALIDATION,
                f"artifact.{executable}",
            )
        if executable == "terraform" and lowered[:1] == ("validate",):
            return _matched(VerificationKind.ARTIFACT_VALIDATION, "artifact.terraform_validate")
        if executable == "ajv" and lowered[:1] == ("validate",):
            return _matched(VerificationKind.ARTIFACT_VALIDATION, "artifact.ajv_validate")
        if executable == "openapi-generator" and lowered[:1] == ("validate",):
            return _matched(VerificationKind.ARTIFACT_VALIDATION, "artifact.openapi_validate")
        if executable == "docker" and lowered[:2] == ("compose", "config") and "--quiet" in lowered:
            return _matched(VerificationKind.ARTIFACT_VALIDATION, "artifact.compose_config_quiet")

        if executable == "cmake" and lowered[:1] == ("--build",):
            return _matched(VerificationKind.BUILD, "build.cmake")
        if executable == "msbuild" and not any(
            argument in {"-version", "-help"} for argument in lowered
        ):
            return _matched(VerificationKind.BUILD, "build.msbuild")

        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

    @staticmethod
    def _classify_package_tool(
        executable: str, arguments: tuple[str, ...]
    ) -> VerificationClassification:
        if (
            executable == "npm"
            and arguments[:1] == ("audit",)
            and "fix" not in arguments[1:]
        ):
            return _matched(VerificationKind.SECURITY, "security.npm_audit")
        if arguments[:1] in {
            ("add",),
            ("ci",),
            ("install",),
            ("remove",),
            ("uninstall",),
        }:
            return _known_non_verification("nonverification.package_management")
        # Package scripts are arbitrary until a separately consented manifest
        # resolver proves their expansion.  Their names are not evidence.
        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

    @staticmethod
    def _classify_python_module(arguments: tuple[str, ...]) -> VerificationClassification:
        if len(arguments) < 2 or arguments[0] != "-m":
            if arguments[:1] == ("-c",):
                return _known_non_verification("nonverification.inline_program")
            return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)
        module = arguments[1]
        if module in {"pytest", "unittest"}:
            return _matched(VerificationKind.TEST, f"test.python_{module}")
        if module in {"mypy", "pyright"}:
            return _matched(VerificationKind.TYPE_CHECK, f"type_check.python_{module}")
        if module in {"bandit", "pip_audit"}:
            return _matched(VerificationKind.SECURITY, f"security.python_{module}")
        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

    @staticmethod
    def _classify_cargo(arguments: tuple[str, ...]) -> VerificationClassification:
        if arguments[:1] == ("test",) and "--no-run" not in arguments:
            return _matched(VerificationKind.TEST, "test.cargo")
        if arguments[:1] == ("build",):
            return _matched(VerificationKind.BUILD, "build.cargo")
        if arguments[:1] == ("clippy",):
            return _matched(VerificationKind.LINT, "lint.cargo_clippy")
        if arguments[:1] == ("check",):
            return _matched(VerificationKind.TYPE_CHECK, "type_check.cargo")
        if arguments[:1] == ("audit",):
            return _matched(VerificationKind.SECURITY, "security.cargo_audit")
        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

    @staticmethod
    def _classify_go(arguments: tuple[str, ...]) -> VerificationClassification:
        if arguments[:1] == ("test",) and "-list" not in arguments[1:]:
            return _matched(VerificationKind.TEST, "test.go")
        if arguments[:1] == ("build",):
            return _matched(VerificationKind.BUILD, "build.go")
        if arguments[:1] == ("vet",):
            return _matched(VerificationKind.LINT, "lint.go_vet")
        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

    @staticmethod
    def _classify_dotnet(arguments: tuple[str, ...]) -> VerificationClassification:
        if arguments[:1] == ("test",):
            return _matched(VerificationKind.TEST, "test.dotnet")
        if arguments[:1] == ("build",):
            return _matched(VerificationKind.BUILD, "build.dotnet")
        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

    @staticmethod
    def _classify_maven(arguments: tuple[str, ...]) -> VerificationClassification:
        goals = {argument for argument in arguments if not argument.startswith("-")}
        skips_tests = any(
            argument.startswith("-dskiptests")
            or argument.startswith("-dmaven.test.skip")
            for argument in arguments
        )
        if ("verify" in goals or "test" in goals) and not skips_tests:
            return _matched(VerificationKind.TEST, "test.maven")
        if "package" in goals:
            return _matched(VerificationKind.BUILD, "build.maven")
        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)

    @staticmethod
    def _classify_gradle(arguments: tuple[str, ...]) -> VerificationClassification:
        tasks = {argument for argument in arguments if not argument.startswith("-")}
        excludes_test = "-m" in arguments or any(
            arguments[index] in {"-x", "--exclude-task"}
            and index + 1 < len(arguments)
            and arguments[index + 1] == "test"
            for index in range(len(arguments))
        )
        if "test" in tasks and not excludes_test:
            return _matched(VerificationKind.TEST, "test.gradle")
        if "build" in tasks or "assemble" in tasks:
            return _matched(VerificationKind.BUILD, "build.gradle")
        return _abstain(VerificationAbstentionReason.UNSUPPORTED_SIGNATURE)


def validation_only_capability() -> VerificationCapability:
    """Describe the shipped classifier without authorizing live provider use."""

    return VerificationCapability(
        state=VerificationCapabilityState.VALIDATION_ONLY,
        live_classification_enabled=False,
        classifier_version=CLASSIFIER_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        candidate_schema_version=CANDIDATE_SCHEMA_VERSION,
        supported_kinds=tuple(VerificationKind),
        reason_code="provider_adapter_and_holdout_required",
    )

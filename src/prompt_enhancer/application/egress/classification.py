"""Auditable egress classification for every direct network boundary."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ...domain import StrictModel


class EgressClass(StrEnum):
    NONE = "none"
    LOOPBACK_OWNED_SERVICE = "loopback_owned_service"
    SIGNED_UPDATE_ADVISORY = "signed_update_advisory"
    APPROVED_MODEL_DOWNLOAD = "approved_model_download"
    APPROVED_PROVIDER_REQUEST = "approved_provider_request"


class FutureEgressState(StrEnum):
    ACTIVE_LOCAL_ONLY = "active_local_only"
    ACTIVE_EXPLICIT_APPROVAL = "active_explicit_approval"
    IMPLEMENTED_UNCOMPOSED = "implemented_uncomposed"
    DECLARED_UNIMPLEMENTED = "declared_unimplemented"


class EgressRegistration(StrictModel):
    module: str = Field(pattern=r"^prompt_enhancer(?:\.[a-zA-Z0-9_]+)+$")
    egress_class: EgressClass
    state: FutureEgressState
    reason_code: str = Field(pattern=r"^[a-z0-9_]{3,64}$")

    @model_validator(mode="after")
    def prevent_inconsistent_claims(self) -> EgressRegistration:
        if (
            self.egress_class in {EgressClass.NONE, EgressClass.LOOPBACK_OWNED_SERVICE}
            and self.state is not FutureEgressState.ACTIVE_LOCAL_ONLY
        ):
            raise ValueError("local registrations require the local-only state")
        if (
            self.egress_class is EgressClass.SIGNED_UPDATE_ADVISORY
            and self.state
            not in {
                FutureEgressState.IMPLEMENTED_UNCOMPOSED,
                FutureEgressState.ACTIVE_EXPLICIT_APPROVAL,
            }
        ):
            raise ValueError("signed update transport state is invalid")
        return self


EGRESS_REGISTRY: tuple[EgressRegistration, ...] = (
    EgressRegistration(module="prompt_enhancer.desktop_overlay", egress_class=EgressClass.LOOPBACK_OWNED_SERVICE, state=FutureEgressState.ACTIVE_LOCAL_ONLY, reason_code="owned_loopback_probe_and_open"),
    EgressRegistration(module="prompt_enhancer.api", egress_class=EgressClass.NONE, state=FutureEgressState.ACTIVE_LOCAL_ONLY, reason_code="url_parse_only"),
    EgressRegistration(module="prompt_enhancer.interfaces.http.desktop_identity", egress_class=EgressClass.NONE, state=FutureEgressState.ACTIVE_LOCAL_ONLY, reason_code="origin_parse_only"),
    EgressRegistration(module="prompt_enhancer.infrastructure.providers.codex_app_server.transports.stdio_jsonl", egress_class=EgressClass.NONE, state=FutureEgressState.ACTIVE_LOCAL_ONLY, reason_code="bounded_child_stdio_only"),
    EgressRegistration(module="prompt_enhancer.infrastructure.text_models.loader", egress_class=EgressClass.APPROVED_MODEL_DOWNLOAD, state=FutureEgressState.ACTIVE_EXPLICIT_APPROVAL, reason_code="reviewed_public_pin_download_opt_in"),
    # Local model runtimes (ADR 0013): the only direct network use is loopback
    # traffic to an owned llama-server child (free-port bind, health, chat
    # proxy). Weights downloads delegate to huggingface_hub and happen only
    # after a size-confirmed approval through the person's own login.
    EgressRegistration(module="prompt_enhancer.application.local_models", egress_class=EgressClass.LOOPBACK_OWNED_SERVICE, state=FutureEgressState.ACTIVE_LOCAL_ONLY, reason_code="owned_loopback_model_runtime"),
    # Prompt-check hook (ADR 0015): a Claude Code hook process posting the
    # person's prompt to this app's own loopback API and printing the advice.
    EgressRegistration(module="prompt_enhancer.interfaces.hooks.prompt_check_hook", egress_class=EgressClass.LOOPBACK_OWNED_SERVICE, state=FutureEgressState.ACTIVE_LOCAL_ONLY, reason_code="owned_loopback_prompt_check_hook"),
    # Controller bridge (ADR 0016): one exact HTTP origin that has already
    # passed the loopback-only constructor boundary. Proxies and redirects are
    # disabled, response sizes are bounded, and the bridge never starts the app.
    EgressRegistration(module="prompt_enhancer.infrastructure.agent_controller_http", egress_class=EgressClass.LOOPBACK_OWNED_SERVICE, state=FutureEgressState.ACTIVE_LOCAL_ONLY, reason_code="owned_loopback_agent_controller"),
    # MCP Store discovery fetches bounded public metadata from the documented
    # Official MCP Registry only after a person opens or searches the Store.
    EgressRegistration(module="prompt_enhancer.infrastructure.mcp_registry", egress_class=EgressClass.APPROVED_PROVIDER_REQUEST, state=FutureEgressState.ACTIVE_EXPLICIT_APPROVAL, reason_code="official_mcp_registry_request"),
    # A remote MCP compatibility check dials only the exact reviewed HTTPS
    # origin after native confirmation. DNS is public-only and pinned; proxies,
    # redirects, tool calls, unbounded responses, and persistent hosts are
    # refused by the guarded-host boundary.
    EgressRegistration(module="prompt_enhancer.infrastructure.mcp_guarded_host", egress_class=EgressClass.APPROVED_PROVIDER_REQUEST, state=FutureEgressState.ACTIVE_EXPLICIT_APPROVAL, reason_code="confirmed_mcp_compatibility_probe"),
    # This no-proxy/no-redirect HTTPS source is intentionally uncomposed until
    # an owner-controlled release origin and Ed25519 public key are packaged.
    # Even after composition, only an authenticated same-origin click calls it.
    EgressRegistration(module="prompt_enhancer.infrastructure.updates.https_manifest_source", egress_class=EgressClass.SIGNED_UPDATE_ADVISORY, state=FutureEgressState.IMPLEMENTED_UNCOMPOSED, reason_code="signed_release_manifest_uncomposed"),
    EgressRegistration(module="prompt_enhancer.infrastructure.updates.https_artifact_source", egress_class=EgressClass.SIGNED_UPDATE_ADVISORY, state=FutureEgressState.IMPLEMENTED_UNCOMPOSED, reason_code="signed_release_artifact_uncomposed"),
    EgressRegistration(module="prompt_enhancer.infrastructure.estimator_runners.codex", egress_class=EgressClass.APPROVED_PROVIDER_REQUEST, state=FutureEgressState.IMPLEMENTED_UNCOMPOSED, reason_code="bounded_child_cli_runner_uncomposed"),
    # Prompt Check only: a configured gateway receives the exact redacted
    # model messages after a matching, short-lived preview approval. Provider
    # session context is excluded; TLS and optional leaf pinning stay enabled.
    EgressRegistration(module="prompt_enhancer.infrastructure.litellm", egress_class=EgressClass.APPROVED_PROVIDER_REQUEST, state=FutureEgressState.ACTIVE_EXPLICIT_APPROVAL, reason_code="reviewed_prompt_check_gateway_request"),
    # Shared team folders (ADR 0018): the peer client dials exactly the URL the
    # person typed when joining a teammate's folder; the share action on the
    # serving side is the consent to answer that token. No other destination.
    EgressRegistration(module="prompt_enhancer.application.shared_folders", egress_class=EgressClass.APPROVED_PROVIDER_REQUEST, state=FutureEgressState.ACTIVE_EXPLICIT_APPROVAL, reason_code="joined_peer_folder_sync_opt_in"),
)

FUTURE_EGRESS_STATES: dict[EgressClass, FutureEgressState] = {
    EgressClass.SIGNED_UPDATE_ADVISORY: FutureEgressState.IMPLEMENTED_UNCOMPOSED,
    EgressClass.APPROVED_MODEL_DOWNLOAD: FutureEgressState.ACTIVE_EXPLICIT_APPROVAL,
    EgressClass.APPROVED_PROVIDER_REQUEST: FutureEgressState.IMPLEMENTED_UNCOMPOSED,
}


def classify_network_module(module: str) -> EgressRegistration | None:
    return next((entry for entry in EGRESS_REGISTRY if entry.module == module), None)

from __future__ import annotations

from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


def test_composition_root_builds_services_without_exposing_api_token(tmp_path) -> None:
    application = bootstrap_local_application(AppSettings(home=tmp_path))

    assert application.database.summary()["sessions"] == 0
    assert application.create_ingestion_service() is not None
    assert application.create_requirement_verification_evidence_service() is not None
    assert application.settings.api_token_path.is_file()
    assert not hasattr(application, "api_token")
    assert "token" not in repr(application).casefold()


def test_composition_root_http_adapter_reuses_initialized_store(tmp_path) -> None:
    application = bootstrap_local_application(AppSettings(home=tmp_path))
    http_app = application.create_http_app()

    assert http_app.state.database is application.database
    assert http_app.state.settings is application.settings
    assert (
        "/v1/sessions/{session_id}/requirement-verification-evidence/"
        "opportunity-sets/current"
    ) in http_app.openapi()["paths"]

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.spa_routes import is_spa_navigation_path
from prompt_enhancer.interfaces.http.desktop_identity import (
    DESKTOP_OWNED_INSTANCE_PATH_PREFIX,
)


API_TOKEN = "synthetic-local-api-token-with-safe-length"
ORIGIN = "http://127.0.0.1:8766"
PROJECT_ID = "a" * 64
SESSION_ID = "b" * 64
TASK_ID = "c" * 64
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
MODULE_ASSET = "assets/app-synthetic8.js"


class StaticReadStore:
    def initialize(self) -> None:
        return None


def _build_static_app(tmp_path: Path):
    static_root = tmp_path / "synthetic-dashboard"
    static_root.mkdir()
    (static_root / "index.html").write_text(
        (
            "<!doctype html><div id='root'>Synthetic dashboard</div>"
            f"<script type='module' src='/{MODULE_ASSET}'></script>"
        ),
        encoding="utf-8",
    )
    assets = static_root / "assets"
    assets.mkdir()
    (static_root / MODULE_ASSET).write_text(
        "globalThis.synthetic = true;", encoding="utf-8"
    )
    return create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=StaticReadStore(),
        api_token=API_TOKEN,
        static_directory=static_root,
    )


def test_spa_route_allowlist_matches_frontend_history_shapes() -> None:
    accepted = [
        "",
        "local-sources",
        "analysis-jobs",
        "calibration",
        "calibration/",
        "projects",
        "research/methods",
        "social",
        "social/",
        f"projects/{PROJECT_ID}/overview",
        f"projects/{PROJECT_ID}/sessions",
        f"projects/{PROJECT_ID}/automation",
        f"projects/{PROJECT_ID}/metrics/prompt-quality",
        f"projects/{PROJECT_ID}/sessions/{SESSION_ID}/metrics/reasoning",
        f"tasks/{TASK_ID}/revisions/1",
        f"tasks/{TASK_ID}/revisions/9007199254740991",
    ]
    rejected = [
        "unexpected",
        "analysis-jobs/extra",
        "research",
        "research/private",
        "social/unknown",
        "social.json",
        "missing.js",
        ".env",
        "live",
        "live/",
        "projects/example-label/overview",
        "projects/example-label/automation",
        f"projects/{PROJECT_ID}/automation/extra",
        f"projects/{PROJECT_ID}/metrics/not-registered",
        f"projects/{PROJECT_ID}/sessions/{SESSION_ID}/metrics/tools/extra",
        f"tasks/{TASK_ID}/revisions/0",
        f"tasks/{TASK_ID}/revisions/9007199254740992",
    ]

    assert all(is_spa_navigation_path(path) for path in accepted)
    assert not any(is_spa_navigation_path(path) for path in rejected)


def test_browser_get_and_head_refresh_allowlisted_deep_routes(tmp_path: Path) -> None:
    app = _build_static_app(tmp_path)
    deep_routes = [
        "/local-sources",
        "/analysis-jobs",
        "/calibration",
        "/calibration/",
        "/projects",
        "/research/methods",
        "/social",
        "/social/",
        f"/projects/{PROJECT_ID}/overview",
        f"/projects/{PROJECT_ID}/automation",
        f"/projects/{PROJECT_ID}/sessions",
        f"/projects/{PROJECT_ID}/metrics/prompt-quality",
        f"/projects/{PROJECT_ID}/sessions/{SESSION_ID}/metrics/tools",
        f"/tasks/{TASK_ID}/revisions/2",
    ]

    with TestClient(app, base_url=ORIGIN) as client:
        for path in deep_routes:
            get_response = client.get(path, headers={"Accept": BROWSER_ACCEPT})
            head_response = client.head(path, headers={"Accept": BROWSER_ACCEPT})

            assert get_response.status_code == 200
            assert "Synthetic dashboard" in get_response.text
            assert get_response.headers["content-type"].startswith("text/html")
            assert head_response.status_code == 200
            assert head_response.content == b""
            assert head_response.headers["content-type"].startswith("text/html")


def test_spa_fallback_rejects_unknown_malformed_and_extension_paths(tmp_path: Path) -> None:
    app = _build_static_app(tmp_path)
    rejected_routes = [
        "/unexpected",
        "/research",
        "/research/private",
        "/social/unknown",
        "/social.json",
        "/missing.js",
        "/.env",
        "/live",
        "/live/",
        "/%2e%2e/private",
        "/assets/%2e%2e/index.html",
        "/assets/%2E%2E/index.html",
        "/assets/%2e./index.html",
        "/assets/%5c..%5cindex.html",
        "/assets/%252e%252e/index.html",
        f"/assets//{MODULE_ASSET.removeprefix('assets/')}",
        "/local-sources/extra",
        "/projects/example-label/overview",
        f"/projects/{PROJECT_ID}/metrics/not-registered",
        f"/projects/{PROJECT_ID}/sessions/{SESSION_ID}/metrics/tools/extra",
        f"/tasks/{TASK_ID}/revisions/0",
    ]

    with TestClient(app, base_url=ORIGIN) as client:
        for path in rejected_routes:
            response = client.get(path, headers={"Accept": BROWSER_ACCEPT})
            assert response.status_code == 404

        non_browser = client.get("/local-sources", headers={"Accept": "*/*"})
        calibration_non_browser = client.get(
            "/calibration", headers={"Accept": "*/*"}
        )
        asset = client.get(f"/{MODULE_ASSET}", headers={"Accept": "*/*"})

    assert non_browser.status_code == 404
    assert calibration_non_browser.status_code == 404
    assert asset.status_code == 200
    assert "synthetic" in asset.text
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_spa_html_accept_negotiation_is_case_insensitive_and_honors_zero_quality(
    tmp_path: Path,
) -> None:
    app = _build_static_app(tmp_path)

    with TestClient(app, base_url=ORIGIN) as client:
        accepted = client.get(
            "/calibration?synthetic=1", headers={"Accept": "Text/HTML"}
        )
        rejected = [
            client.get("/calibration", headers={"Accept": value})
            for value in (
                "text/html;q=0",
                "text/html;q=0.000,application/xhtml+xml",
                "text/html;q=invalid",
                "application/xhtml+xml,*/*;q=0.8",
            )
        ]

    assert accepted.status_code == 200
    assert "Synthetic dashboard" in accepted.text
    assert all(response.status_code == 404 for response in rejected)
    assert all("Synthetic dashboard" not in response.text for response in rejected)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_spa_fallback_never_serves_html_for_unsupported_methods(
    tmp_path: Path,
    method: str,
) -> None:
    app = _build_static_app(tmp_path)

    with TestClient(app, base_url=ORIGIN) as client:
        response = client.request(
            method,
            "/calibration",
            headers={"Accept": BROWSER_ACCEPT},
        )

    assert response.status_code == 405
    assert "Synthetic dashboard" not in response.text
    assert response.headers["content-type"].startswith("application/json")


def test_app_revision_get_and_head_are_content_free_and_not_spa_fallback(
    tmp_path: Path,
) -> None:
    app = _build_static_app(tmp_path)

    with TestClient(app, base_url=ORIGIN) as client:
        get_response = client.get(
            "/app-revision.json", headers={"Accept": BROWSER_ACCEPT}
        )
        head_response = client.head(
            "/app-revision.json", headers={"Accept": BROWSER_ACCEPT}
        )

    assert get_response.status_code == 200
    assert get_response.json() == {"revision": MODULE_ASSET}
    assert get_response.text == f'{{"revision":"{MODULE_ASSET}"}}'
    assert "Synthetic dashboard" not in get_response.text
    assert get_response.headers["content-type"].startswith("application/json")
    assert get_response.headers["cache-control"] == "no-store"
    assert get_response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in get_response.headers["content-security-policy"]
    assert get_response.headers["referrer-policy"] == "no-referrer"
    assert get_response.headers["x-frame-options"] == "DENY"
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert head_response.headers["content-type"].startswith("application/json")
    assert head_response.headers["cache-control"] == "no-store"


def test_app_revision_tracks_a_new_valid_frontend_build_without_server_restart(
    tmp_path: Path,
) -> None:
    app = _build_static_app(tmp_path)
    static_root = tmp_path / "synthetic-dashboard"
    next_revision = "assets/app-rebuilt88.js"
    (static_root / next_revision).write_text(
        "globalThis.syntheticRevision = 2;", encoding="utf-8"
    )

    with TestClient(app, base_url=ORIGIN) as client:
        initial = client.get("/app-revision.json")
        (static_root / "index.html").write_text(
            (
                "<!doctype html><div id='root'>Synthetic dashboard v2</div>"
                f"<script type='module' src='/{next_revision}'></script>"
            ),
            encoding="utf-8",
        )
        rebuilt = client.get("/app-revision.json")

    assert initial.json() == {"revision": MODULE_ASSET}
    assert rebuilt.status_code == 200
    assert rebuilt.json() == {"revision": next_revision}


def test_app_revision_returns_fixed_safe_503_while_rebuild_is_incoherent(
    tmp_path: Path,
) -> None:
    app = _build_static_app(tmp_path)
    static_root = tmp_path / "synthetic-dashboard"
    private_canary = "SYNTHETIC-PRIVATE-PATH-CANARY"
    (static_root / "index.html").write_text(
        (
            "<!doctype html><div id='root'></div>"
            f"<script type='module' src='/assets/{private_canary}.js'></script>"
        ),
        encoding="utf-8",
    )

    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/app-revision.json")
        head_response = client.head("/app-revision.json")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "dashboard revision temporarily unavailable"
    }
    assert private_canary not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert head_response.status_code == 503
    assert head_response.content == b""
    assert head_response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "module_markup,create_asset",
    [
        ("", False),
        ("<script type='module' src='/assets/app.js'></script>", True),
        ("<script type='module' src='https://example.invalid/app-safehash.js'></script>", False),
        ("<script type='module' src='/assets/app-safehash.js?version=1'></script>", False),
        ("<script type='module' src='/assets/../app-safehash.js'></script>", False),
        ("<script type='module'></script>", False),
        ("<script type='module' src='/assets/app-safehash.js'></script>", False),
        (
            "<script type='module' src='/assets/app-safehash.js'></script>"
            "<script type='module' src='/assets/other-safehash.js'></script>",
            True,
        ),
    ],
)
def test_static_app_creation_rejects_missing_unsafe_or_ambiguous_module_scripts(
    tmp_path: Path,
    module_markup: str,
    create_asset: bool,
) -> None:
    static_root = tmp_path / "synthetic-invalid-dashboard"
    static_root.mkdir()
    (static_root / "index.html").write_text(
        f"<!doctype html><div id='root'></div>{module_markup}", encoding="utf-8"
    )
    assets = static_root / "assets"
    assets.mkdir()
    if create_asset:
        (assets / "app-safehash.js").write_text("synthetic", encoding="utf-8")
        (assets / "other-safehash.js").write_text("synthetic", encoding="utf-8")

    with pytest.raises(
        ValueError, match="integrated dashboard build is unavailable or unsafe"
    ):
        create_app(
            settings=AppSettings(home=tmp_path / "app-home"),
            database=StaticReadStore(),
            api_token=API_TOKEN,
            static_directory=static_root,
        )


def test_spa_fallback_preserves_api_auth_health_and_security_headers(
    tmp_path: Path,
) -> None:
    app = _build_static_app(tmp_path)

    with TestClient(app, base_url=ORIGIN) as client:
        shell = client.get("/projects", headers={"Accept": BROWSER_ACCEPT})
        api_auth = client.get("/v1/capabilities", headers={"Accept": "application/json"})
        api_missing = client.get("/v1/missing", headers={"Accept": BROWSER_ACCEPT})
        health = client.get("/health", headers={"Accept": BROWSER_ACCEPT})

    assert shell.status_code == 200
    assert shell.headers["cache-control"] == "no-store"
    assert shell.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in shell.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in shell.headers["content-security-policy"]
    assert api_auth.status_code == 401
    assert api_missing.status_code == 404
    assert health.status_code == 200
    assert health.headers["content-type"].startswith("application/json")


def test_owned_desktop_readiness_route_precedes_spa_fallback(tmp_path: Path) -> None:
    readiness_path = f"{DESKTOP_OWNED_INSTANCE_PATH_PREFIX}{'s' * 43}"
    static_root = tmp_path / "synthetic-dashboard"
    static_root.mkdir()
    (static_root / "index.html").write_text(
        "<!doctype html><script type='module' src='/assets/app-safehash.js'></script>",
        encoding="utf-8",
    )
    assets = static_root / "assets"
    assets.mkdir()
    (assets / "app-safehash.js").write_text("synthetic", encoding="utf-8")
    app = create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=StaticReadStore(),
        api_token=API_TOKEN,
        static_directory=static_root,
        desktop_owned_readiness_path=readiness_path,
    )

    with TestClient(app, base_url=ORIGIN) as client:
        ready = client.get(readiness_path)
        another_instance = client.get(
            f"{DESKTOP_OWNED_INSTANCE_PATH_PREFIX}{'a' * 43}"
        )

    assert ready.status_code == 204
    assert ready.content == b""
    assert ready.headers["cache-control"] == "no-store"
    assert another_instance.status_code == 404

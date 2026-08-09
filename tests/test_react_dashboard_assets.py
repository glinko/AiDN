from pathlib import Path

from fastapi.testclient import TestClient

import aidn_hypervisor.api as api_module
import aidn_hypervisor.dashboard as dashboard_module
from aidn_hypervisor.main import build_app


def test_react_dashboard_navigation_stays_inside_react_workspace() -> None:
    app_source = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "operator-dashboard"
        / "src"
        / "App.tsx"
    ).read_text(encoding="utf-8")

    assert "id: 'legacy'" not in app_source
    assert "window.location.assign('/operators/dashboard')" not in app_source
    assert "window.history.pushState" in app_source
    for screen in ("agents", "market", "catalog", "wallet", "settings", "providers", "models", "validation", "network"):
        assert f"id: '{screen}'" in app_source


def test_react_dashboard_asset_resolver_requires_a_regular_file(
    monkeypatch, tmp_path
) -> None:
    dashboard_root = tmp_path / "react-dashboard"
    assets = dashboard_root / "assets"
    assets.mkdir(parents=True)
    index = dashboard_root / "index.html"
    index.write_text("<main>AiDN</main>", encoding="utf-8")
    script = assets / "index-test.js"
    script.write_text("console.log('aidn')", encoding="utf-8")
    monkeypatch.setattr(dashboard_module, "react_dashboard_directory", lambda: dashboard_root)

    assert dashboard_module.find_react_dashboard_asset() == index
    assert dashboard_module.find_react_dashboard_asset("assets/index-test.js") == script
    assert dashboard_module.find_react_dashboard_asset("../operator_dashboard.html") is None
    assert dashboard_module.find_react_dashboard_asset("assets/missing.js") is None


def test_react_dashboard_routes_serve_index_and_hashed_assets(monkeypatch, tmp_path) -> None:
    dashboard_root = tmp_path / "react-dashboard"
    assets = dashboard_root / "assets"
    assets.mkdir(parents=True)
    index = dashboard_root / "index.html"
    index.write_text("<main>AiDN</main>", encoding="utf-8")
    script = assets / "index-test.js"
    script.write_text("console.log('aidn')", encoding="utf-8")
    monkeypatch.setattr(
        api_module,
        "find_react_dashboard_asset",
        lambda asset_path=None: index if asset_path is None else script if asset_path == "assets/index-test.js" else None,
    )
    client = TestClient(build_app())

    index_response = client.get("/operators/dashboard/react")
    asset_response = client.get("/operators/dashboard/react/assets/index-test.js")
    missing_response = client.get("/operators/dashboard/react/assets/missing.js")

    assert index_response.status_code == 200
    assert index_response.headers["cache-control"] == "no-store"
    assert index_response.text == "<main>AiDN</main>"
    assert asset_response.status_code == 200
    assert asset_response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert asset_response.text == "console.log('aidn')"
    assert missing_response.status_code == 404

"""The page and local assets work without database/provider availability."""

import re

from fastapi.testclient import TestClient

from app.main import create_app


def test_ui_and_assets_are_available_without_provider_calls(settings, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Opening the UI must not invoke a provider")

    monkeypatch.setattr("app.api.chat.ask", forbidden)
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Synthetic demo" in page.text
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert "unsafe-inline" not in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-cache"
        for asset in ("app.js", "app.css"):
            url = re.search(rf'"(/assets/{re.escape(asset)}\?v=[a-f0-9]{{16}})"', page.text)
            assert url is not None and client.get(url[1]).status_code == 200
        for asset, mime in [
            ("app.js", "javascript"),
            ("app.css", "text/css"),
            ("icon.svg", "image/svg+xml"),
        ]:
            result = client.get(f"/assets/{asset}")
            assert result.status_code == 200
            assert mime in result.headers["content-type"]
        assert client.get("/demo").json()["synthetic"] is True
        assert "/api/chat" in client.get("/openapi.json").json()["paths"]
        assert client.get("/docs").status_code == 200


def test_ui_asset_version_changes_with_content(settings, monkeypatch, tmp_path):
    from app.api import ui

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<script src="/assets/app.js"></script>')
    (tmp_path / "assets/app.js").write_text("old script")
    (tmp_path / "assets/app.css").write_text("styles")
    monkeypatch.setattr(ui, "UI_DIRECTORY", tmp_path)
    with TestClient(create_app(settings)) as client:
        before = client.get("/").text
        (tmp_path / "assets/app.js").write_text("updated script")
        after = client.get("/").text
    assert before != after


def test_static_mount_does_not_publish_source_or_local_secrets(settings):
    with TestClient(create_app(settings)) as client:
        for path in [
            "/assets/.env",
            "/assets/index.html",
            "/assets/../config.py",
            "/assets/%2e%2e/config.py",
            "/QUERYLENS_PLAN.md",
            "/docs/setup.md",
        ]:
            assert client.get(path).status_code == 404
